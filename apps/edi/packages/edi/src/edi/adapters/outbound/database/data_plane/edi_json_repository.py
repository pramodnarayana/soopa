from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import cast

from seedwork.domain.types import JsonValue
from seedwork.events import EventEnvelope
from seedwork.utils import generate_id
from sqlalchemy import and_, select, update

from database.exceptions import DuplicateEntityError
from edi.adapters.outbound.database.data_plane.stage_repository_base import (
    DataPlaneStageSqlAlchemyRepository,
)
from edi.adapters.outbound.database.models.data_plane import EdiJson as OrmEdiJson
from edi.adapters.outbound.database.payload_hydration import hydrate_json_payload
from edi.domain.constants import EdiIdPrefix as DomainIdPrefix
from edi.domain.exceptions import IdempotencyConflictError
from edi.domain.routing.enums import Direction
from edi.domain.transaction.edi_json import EdiJson
from edi.domain.transaction.enums import MessageStatus
from edi.domain.transaction.stage_filter import StageFilterCriterion
from edi.ports.outbound.edi_json_repository import EdiJsonRepositoryPort


class SqlAlchemyEdiJsonRepository(DataPlaneStageSqlAlchemyRepository, EdiJsonRepositoryPort):
    @staticmethod
    def _to_domain_model(record: OrmEdiJson, hydrated_payload: JsonValue | None = None) -> EdiJson:
        """Explicit ORM -> Domain mapper for EdiJson."""
        return EdiJson(
            id=str(record.id),
            trace_id=str(record.trace_id),
            tenant_id=str(record.tenant_id),
            direction=Direction(record.direction) if record.direction else Direction.OUTBOUND,
            status=MessageStatus(record.status) if record.status else MessageStatus.PENDING,
            created_at=record.created_at,
            updated_at=record.updated_at,
            status_message=record.status_message,
            error_code=record.error_code,
            error_details=record.error_details,
            trading_partner_id=record.trading_partner_id,
            transaction_type=record.transaction_type,
            standard=record.standard,
            business_metadata=record.business_metadata,
            payload=hydrated_payload if hydrated_payload is not None else record.payload,
            storage_uri=record.storage_uri,
            replay_count=record.replay_count,
            parent_trace_id=record.parent_trace_id,
            original_trace_id=record.original_trace_id,
        )

    @staticmethod
    def _to_orm_record(aggregate: EdiJson) -> OrmEdiJson:
        """Explicit Domain -> ORM mapper for EdiJson."""
        record_id = aggregate.id if aggregate.id else generate_id(DomainIdPrefix.EDI_JSON.value)
        return OrmEdiJson(
            id=record_id,
            trace_id=aggregate.trace_id,
            tenant_id=aggregate.tenant_id,
            direction=aggregate.direction.value if aggregate.direction else None,
            status=aggregate.status.value if aggregate.status else None,
            status_message=aggregate.status_message,
            error_code=aggregate.error_code,
            error_details=aggregate.error_details,
            trading_partner_id=aggregate.trading_partner_id,
            transaction_type=aggregate.transaction_type,
            standard=aggregate.standard,
            business_metadata=aggregate.business_metadata,
            payload=cast(dict[str, JsonValue] | None, aggregate.payload),
            storage_uri=aggregate.storage_uri,
            replay_count=aggregate.replay_count,
            parent_trace_id=aggregate.parent_trace_id,
            original_trace_id=aggregate.original_trace_id,
        )

    @staticmethod
    def _update_record_from_domain(record: OrmEdiJson, aggregate: EdiJson) -> None:
        """Explicit Domain -> ORM mutation mapper for EdiJson."""
        if aggregate.direction:
            record.direction = aggregate.direction.value
        if aggregate.status:
            record.status = aggregate.status.value
        record.status_message = aggregate.status_message
        record.error_code = aggregate.error_code
        record.error_details = aggregate.error_details
        record.trading_partner_id = aggregate.trading_partner_id
        record.transaction_type = aggregate.transaction_type
        record.standard = aggregate.standard
        record.business_metadata = aggregate.business_metadata
        record.payload = cast(dict[str, JsonValue] | None, aggregate.payload)
        record.storage_uri = aggregate.storage_uri
        record.replay_count = aggregate.replay_count
        record.parent_trace_id = aggregate.parent_trace_id
        record.original_trace_id = aggregate.original_trace_id

    async def update_edi_json_routing_metadata(
        self,
        trace_id: str,
        *,
        trading_partner_id: str | None = None,
        standard: str | None = None,
    ) -> None:
        if trading_partner_id is None and standard is None:
            return

        stmt = update(OrmEdiJson).where(OrmEdiJson.trace_id == str(trace_id))
        if trading_partner_id is not None:
            stmt = stmt.values(trading_partner_id=trading_partner_id)
        if standard is not None:
            stmt = stmt.values(standard=standard)

        await self.session.execute(stmt)

    async def update_edi_json_status(self, trace_id: str, status: MessageStatus) -> None:
        stmt = (
            update(OrmEdiJson)
            .where(OrmEdiJson.trace_id == str(trace_id))
            .values(status=status.value)
        )
        await self.session.execute(stmt)

    async def save(self, aggregate: EdiJson) -> Sequence[EventEnvelope]:
        if (
            aggregate.direction == Direction.INBOUND
            and aggregate.trace_id
            and aggregate.transaction_type
        ):
            stmt = (
                select(OrmEdiJson)
                .where(
                    OrmEdiJson.tenant_id == aggregate.tenant_id,
                    OrmEdiJson.trace_id == aggregate.trace_id,
                    OrmEdiJson.direction == aggregate.direction.value,
                    OrmEdiJson.transaction_type == aggregate.transaction_type,
                )
                .limit(1)
            )
            result = await self.session.execute(stmt)
            existing_record = result.scalar_one_or_none()
            if existing_record is not None:
                self._update_record_from_domain(existing_record, aggregate)
                await self.flush()
                return await self._drain_stage_events(aggregate)

        record = self._to_orm_record(aggregate)
        try:
            async with self.session.begin_nested():
                await self.session.merge(record)
                await self.flush()
        except DuplicateEntityError as exc:
            raise IdempotencyConflictError(
                f"EdiJson with idempotency key already exists: {exc}"
            ) from exc

        return await self._drain_stage_events(aggregate)

    async def flush_events(self, aggregate: EdiJson) -> Sequence[EventEnvelope]:
        return await self._drain_stage_events(aggregate)

    async def get_edi_json(self, trace_id: str, tenant_id: str | None = None) -> EdiJson | None:
        stmt = (
            select(OrmEdiJson)
            .where(OrmEdiJson.trace_id == str(trace_id))
            .order_by(OrmEdiJson.created_at.desc())
            .limit(1)
        )
        if tenant_id:
            stmt = stmt.where(OrmEdiJson.tenant_id == tenant_id)
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        if not record:
            return None

        payload = await hydrate_json_payload(self.storage, record.storage_uri, record.payload)
        return self._to_domain_model(record, payload)

    async def get_edi_jsons_by_trace_id(
        self, trace_id: str, tenant_id: str | None = None
    ) -> list[EdiJson]:
        stmt = (
            select(OrmEdiJson)
            .where(OrmEdiJson.trace_id == str(trace_id))
            .order_by(OrmEdiJson.created_at.asc())
        )
        if tenant_id:
            stmt = stmt.where(OrmEdiJson.tenant_id == tenant_id)
        result = await self.session.execute(stmt)
        records = result.scalars().all()
        if not records:
            return []

        hydrated_payloads = await asyncio.gather(
            *(hydrate_json_payload(self.storage, j.storage_uri, j.payload) for j in records)
        )
        return [
            self._to_domain_model(record, payload)
            for record, payload in zip(records, hydrated_payloads, strict=True)
        ]

    async def get_edi_json_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> EdiJson | None:
        stmt = (
            select(OrmEdiJson)
            .where(
                OrmEdiJson.tenant_id == tenant_id,
                OrmEdiJson.business_metadata.op("@>")({"_idempotency_key": idempotency_key}),
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        record = result.scalars().first()
        if not record:
            return None

        payload = await hydrate_json_payload(self.storage, record.storage_uri, record.payload)
        return self._to_domain_model(record, payload)

    async def list_edi_json(self, tenant_id: str, key: str, value: str) -> Sequence[EdiJson]:
        tid_str = tenant_id if tenant_id is not None else None
        json_stmt = (
            select(OrmEdiJson)
            .where(
                OrmEdiJson.tenant_id == tid_str,
                OrmEdiJson.business_metadata.contains({key: value}),
            )
            .order_by(OrmEdiJson.created_at.asc())
        )
        result = await self.session.execute(json_stmt)
        records = result.scalars().all()
        if not records:
            return []

        hydrated_payloads = await asyncio.gather(
            *(hydrate_json_payload(self.storage, r.storage_uri, r.payload) for r in records)
        )
        return [
            self._to_domain_model(record, payload)
            for record, payload in zip(records, hydrated_payloads, strict=True)
        ]

    async def explorer_list_edi_json(
        self,
        tenant_id: str,
        filters: Sequence[StageFilterCriterion],
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[EdiJson]:
        tid_str = tenant_id if tenant_id is not None else None
        base_stmt = select(OrmEdiJson).where(OrmEdiJson.tenant_id == tid_str)
        stmt = self._apply_dynamic_filters(base_stmt, OrmEdiJson, filters)
        stmt = stmt.order_by(OrmEdiJson.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        records = result.scalars().all()
        if not records:
            return []

        hydrated_payloads = await asyncio.gather(
            *(hydrate_json_payload(self.storage, j.storage_uri, j.payload) for j in records)
        )
        return [
            self._to_domain_model(record, payload)
            for record, payload in zip(records, hydrated_payloads, strict=True)
        ]

    async def increment_replay_count(self, tenant_id: str, trace_ids: Sequence[str]) -> None:
        if not trace_ids:
            return
        trace_id_strs = [str(tid) for tid in trace_ids]
        stmt = (
            update(OrmEdiJson)
            .where(
                and_(
                    OrmEdiJson.tenant_id == tenant_id,
                    OrmEdiJson.trace_id.in_(trace_id_strs),
                )
            )
            .values(replay_count=OrmEdiJson.replay_count + 1)
        )
        await self.session.execute(stmt)
