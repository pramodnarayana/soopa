from __future__ import annotations

import asyncio
from collections.abc import Sequence

import structlog
from seedwork.events import EventEnvelope
from seedwork.utils import generate_id
from sqlalchemy import and_, or_, select, update

from database.exceptions import DuplicateEntityError
from database.outbox_serializer import serialize_domain_event
from edi.adapters.outbound.database.data_plane.stage_repository_base import (
    DataPlaneStageSqlAlchemyRepository,
    event_idempotency_key,
)
from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox
from edi.adapters.outbound.database.models.data_plane import EdiMessage as OrmEdiMessage
from edi.adapters.outbound.database.payload_hydration import hydrate_edi_data
from edi.domain.constants import EdiIdPrefix as DomainIdPrefix
from edi.domain.enums import EdiOutboxSource
from edi.domain.routing.enums import Direction
from edi.domain.transaction.edi_message import EdiMessage
from edi.domain.transaction.enums import MessageStatus, RecordStatus
from edi.domain.transaction.stage_filter import StageFilterCriterion
from edi.ports.outbound.edi_message_repository import EdiMessageRepositoryPort

logger = structlog.get_logger(__name__)


class SqlAlchemyEdiMessageRepository(DataPlaneStageSqlAlchemyRepository, EdiMessageRepositoryPort):
    @staticmethod
    def _to_domain_model(record: OrmEdiMessage, hydrated_edi_data: str | None = None) -> EdiMessage:
        """Explicit ORM -> Domain mapper for EdiMessage."""
        return EdiMessage(
            id=str(record.id),
            tenant_id=str(record.tenant_id),
            trace_id=str(record.trace_id),
            direction=Direction(record.direction),
            status=RecordStatus(record.status),
            created_at=record.created_at,
            updated_at=record.updated_at,
            format_standard=record.format_standard,
            transaction_type=record.transaction_type,
            connection_type=record.connection_type,
            sender_id=record.sender_id,
            receiver_id=record.receiver_id,
            gs_sender_id=record.gs_sender_id,
            gs_receiver_id=record.gs_receiver_id,
            as2_sender_id=record.as2_sender_id,
            as2_receiver_id=record.as2_receiver_id,
            message_id=record.message_id,
            mdn_id=record.mdn_id,
            mdn_mode=record.mdn_mode,
            mdn_response=record.mdn_response,
            file_name=record.file_name,
            content_type=record.content_type,
            signature_algorithm=record.signature_algorithm,
            encryption_algorithm=record.encryption_algorithm,
            status_message=record.status_message,
            error_code=record.error_code,
            error_details=record.error_details,
            state=record.state,
            msg_headers=record.msg_headers,
            edi_data=hydrated_edi_data if hydrated_edi_data is not None else record.edi_data,
            trading_partner_id=record.trading_partner_id,
            storage_uri=record.storage_uri,
            interchange_control_no=record.interchange_control_no,
            file_size_bytes=record.file_size_bytes,
            replay_count=record.replay_count,
            parent_trace_id=record.parent_trace_id,
            original_trace_id=record.original_trace_id,
        )

    @staticmethod
    def _to_orm_record(aggregate: EdiMessage) -> OrmEdiMessage:
        """Explicit Domain -> ORM mapper for EdiMessage."""
        record_id = aggregate.id if aggregate.id else generate_id(DomainIdPrefix.EDI_MESSAGE.value)
        return OrmEdiMessage(
            id=record_id,
            trace_id=aggregate.trace_id,
            tenant_id=aggregate.tenant_id,
            direction=aggregate.direction.value if aggregate.direction else None,
            status=aggregate.status.value if aggregate.status else None,
            format_standard=aggregate.format_standard,
            transaction_type=aggregate.transaction_type,
            connection_type=aggregate.connection_type,
            sender_id=aggregate.sender_id,
            receiver_id=aggregate.receiver_id,
            gs_sender_id=aggregate.gs_sender_id,
            gs_receiver_id=aggregate.gs_receiver_id,
            as2_sender_id=aggregate.as2_sender_id,
            as2_receiver_id=aggregate.as2_receiver_id,
            message_id=aggregate.message_id,
            mdn_id=aggregate.mdn_id,
            mdn_mode=aggregate.mdn_mode,
            mdn_response=aggregate.mdn_response,
            file_name=aggregate.file_name,
            content_type=aggregate.content_type,
            signature_algorithm=aggregate.signature_algorithm,
            encryption_algorithm=aggregate.encryption_algorithm,
            status_message=aggregate.status_message,
            error_code=aggregate.error_code,
            error_details=aggregate.error_details,
            state=aggregate.state,
            msg_headers=aggregate.msg_headers,
            trading_partner_id=aggregate.trading_partner_id,
            edi_data=aggregate.edi_data,
            storage_uri=aggregate.storage_uri,
            interchange_control_no=aggregate.interchange_control_no,
            file_size_bytes=aggregate.file_size_bytes,
            replay_count=aggregate.replay_count,
            parent_trace_id=aggregate.parent_trace_id,
            original_trace_id=aggregate.original_trace_id,
        )

    @staticmethod
    def _update_record_from_domain(record: OrmEdiMessage, aggregate: EdiMessage) -> None:
        """Explicit Domain -> ORM mutation mapper for EdiMessage."""
        if aggregate.direction:
            record.direction = aggregate.direction.value
        if aggregate.status:
            record.status = aggregate.status.value
        record.format_standard = aggregate.format_standard
        record.transaction_type = aggregate.transaction_type
        record.connection_type = aggregate.connection_type
        record.sender_id = aggregate.sender_id
        record.receiver_id = aggregate.receiver_id
        record.gs_sender_id = aggregate.gs_sender_id
        record.gs_receiver_id = aggregate.gs_receiver_id
        record.as2_sender_id = aggregate.as2_sender_id
        record.as2_receiver_id = aggregate.as2_receiver_id
        record.message_id = aggregate.message_id
        record.mdn_id = aggregate.mdn_id
        record.mdn_mode = aggregate.mdn_mode
        record.mdn_response = aggregate.mdn_response
        record.file_name = aggregate.file_name
        record.content_type = aggregate.content_type
        record.signature_algorithm = aggregate.signature_algorithm
        record.encryption_algorithm = aggregate.encryption_algorithm
        record.status_message = aggregate.status_message
        record.error_code = aggregate.error_code
        record.error_details = aggregate.error_details
        record.state = aggregate.state
        record.msg_headers = aggregate.msg_headers
        record.trading_partner_id = aggregate.trading_partner_id
        record.edi_data = aggregate.edi_data
        record.storage_uri = aggregate.storage_uri
        record.interchange_control_no = aggregate.interchange_control_no
        record.file_size_bytes = aggregate.file_size_bytes
        record.replay_count = aggregate.replay_count
        record.parent_trace_id = aggregate.parent_trace_id
        record.original_trace_id = aggregate.original_trace_id

    async def update_edi_message_metadata(
        self,
        trace_id: str,
        gs_sender_id: str | None,
        gs_receiver_id: str | None,
        transaction_type: str | None,
    ) -> None:
        stmt = (
            update(OrmEdiMessage)
            .where(OrmEdiMessage.trace_id == str(trace_id))
            .values(
                gs_sender_id=gs_sender_id,
                gs_receiver_id=gs_receiver_id,
            )
        )
        if transaction_type is not None:
            stmt = stmt.values(transaction_type=transaction_type)
        await self.session.execute(stmt)

    async def update_edi_message_status(self, trace_id: str, status: MessageStatus) -> None:
        stmt = (
            update(OrmEdiMessage)
            .where(OrmEdiMessage.trace_id == str(trace_id))
            .values(status=status.value)
        )
        await self.session.execute(stmt)

    async def update_outbound_delivery_metadata(self, aggregate: EdiMessage) -> None:
        stmt = (
            update(OrmEdiMessage)
            .where(OrmEdiMessage.id == str(aggregate.id))
            .values(
                status=aggregate.status.value if aggregate.status else None,
                connection_type=aggregate.connection_type,
                trading_partner_id=aggregate.trading_partner_id,
                message_id=aggregate.message_id,
                as2_sender_id=aggregate.as2_sender_id,
                as2_receiver_id=aggregate.as2_receiver_id,
                mdn_id=aggregate.mdn_id,
                mdn_mode=aggregate.mdn_mode,
                mdn_response=aggregate.mdn_response,
                signature_algorithm=aggregate.signature_algorithm,
                encryption_algorithm=aggregate.encryption_algorithm,
                status_message=aggregate.status_message,
                error_code=aggregate.error_code,
                error_details=aggregate.error_details,
                state=aggregate.state,
                msg_headers=aggregate.msg_headers,
                file_name=aggregate.file_name,
                content_type=aggregate.content_type,
            )
        )
        await self.session.execute(stmt)

    async def save(self, aggregate: EdiMessage) -> Sequence[EventEnvelope]:
        await self.session.merge(self._to_orm_record(aggregate))
        return await self._drain_stage_events(aggregate)

    async def flush_events(self, aggregate: EdiMessage) -> Sequence[EventEnvelope]:
        return await self._drain_stage_events(aggregate)

    async def save_all(self, aggregates: Sequence[EdiMessage]) -> Sequence[EventEnvelope]:
        records: list[OrmEdiMessage] = []
        pending_outbox: list[tuple[DataPlaneOutbox, EventEnvelope]] = []

        for aggregate in aggregates:
            records.append(self._to_orm_record(aggregate))
            event_count = len(aggregate.domain_events)
            for index, event in enumerate(aggregate.domain_events):
                event_id = generate_id(DomainIdPrefix.EDI_DP_OUTBOX.value)
                idempotency_key = event_idempotency_key(
                    event.idempotency_key,
                    index=index,
                    event_count=event_count,
                )
                payload_dict = serialize_domain_event(event)
                tenant_id = event.get_routing_tenant_id() or aggregate.tenant_id
                pending_outbox.append(
                    (
                        DataPlaneOutbox(
                            id=event_id,
                            tenant_id=tenant_id,
                            idempotency_key=idempotency_key,
                            event_type=event.event_name,
                            payload=payload_dict,
                        ),
                        EventEnvelope(
                            id=event_id,
                            source=EdiOutboxSource.EDI_DATA_PLANE,
                            tenant_id=tenant_id,
                            event_type=event.event_name,
                            payload=payload_dict,
                            idempotency_key=idempotency_key,
                        ),
                    )
                )

        for record in records:
            await self.session.merge(record)

        envelopes: list[EventEnvelope] = []
        for outbox_record, envelope in pending_outbox:
            try:
                async with self.session.begin_nested():
                    self.session.add(outbox_record)
                    await self.flush()
                envelopes.append(envelope)
            except DuplicateEntityError:
                logger.info(
                    "edi_stage_outbox_event_deduplicated",
                    idempotency_key=outbox_record.idempotency_key,
                    event_type=outbox_record.event_type,
                    tenant_id=outbox_record.tenant_id,
                )

        for aggregate in aggregates:
            await self._persist_trace_events(aggregate)
            aggregate.clear_domain_events()

        return envelopes

    async def get_edi_message(
        self, trace_id: str, tenant_id: str | None = None
    ) -> EdiMessage | None:
        stmt = (
            select(OrmEdiMessage)
            .where(OrmEdiMessage.trace_id == str(trace_id))
            .order_by(OrmEdiMessage.created_at.desc())
            .limit(1)
        )
        if tenant_id:
            stmt = stmt.where(OrmEdiMessage.tenant_id == tenant_id)
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        if not record:
            return None

        hydrated_payload = await hydrate_edi_data(self.storage, record.storage_uri, record.edi_data)
        return self._to_domain_model(record, hydrated_payload)

    async def get_edi_messages_by_traces(
        self, tenant_id: str, trace_ids: Sequence[str]
    ) -> Sequence[EdiMessage]:
        if not trace_ids:
            return []

        stmt = (
            select(OrmEdiMessage)
            .distinct(OrmEdiMessage.trace_id)
            .where(
                and_(
                    OrmEdiMessage.trace_id.in_([str(tid) for tid in trace_ids]),
                    OrmEdiMessage.tenant_id == tenant_id,
                )
            )
            .order_by(OrmEdiMessage.trace_id, OrmEdiMessage.created_at.desc())
        )
        result = await self.session.execute(stmt)
        records = result.scalars().all()
        if not records:
            return []

        hydrated_payloads = await asyncio.gather(
            *(hydrate_edi_data(self.storage, r.storage_uri, r.edi_data) for r in records)
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
            update(OrmEdiMessage)
            .where(
                and_(
                    OrmEdiMessage.tenant_id == tenant_id,
                    OrmEdiMessage.trace_id.in_(trace_id_strs),
                )
            )
            .values(replay_count=OrmEdiMessage.replay_count + 1)
        )
        await self.session.execute(stmt)

    async def list_edi_messages(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        partner_id: str | None = None,
        transaction_type: str | None = None,
        direction: str | None = None,
    ) -> Sequence[EdiMessage]:
        limit = min(max(1, limit), 200)
        offset = max(0, offset)

        tid_str = tenant_id if tenant_id is not None else None
        stmt = select(OrmEdiMessage).where(OrmEdiMessage.tenant_id == tid_str)
        if direction:
            stmt = stmt.where(OrmEdiMessage.direction == direction)
        if transaction_type:
            stmt = stmt.where(OrmEdiMessage.transaction_type == transaction_type)
        if partner_id:
            stmt = stmt.where(
                or_(
                    OrmEdiMessage.sender_id == partner_id,
                    OrmEdiMessage.receiver_id == partner_id,
                    OrmEdiMessage.gs_sender_id == partner_id,
                    OrmEdiMessage.gs_receiver_id == partner_id,
                )
            )
        stmt = stmt.order_by(OrmEdiMessage.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        records = result.scalars().all()
        if not records:
            return []

        hydrated_payloads = await asyncio.gather(
            *(hydrate_edi_data(self.storage, r.storage_uri, r.edi_data) for r in records)
        )
        return [
            self._to_domain_model(record, payload)
            for record, payload in zip(records, hydrated_payloads, strict=True)
        ]

    async def explorer_list_edi_messages(
        self,
        tenant_id: str,
        filters: Sequence[StageFilterCriterion],
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[EdiMessage]:
        tid_str = tenant_id if tenant_id is not None else None
        base_stmt = select(OrmEdiMessage).where(OrmEdiMessage.tenant_id == tid_str)
        stmt = self._apply_dynamic_filters(base_stmt, OrmEdiMessage, filters)
        stmt = stmt.order_by(OrmEdiMessage.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        records = result.scalars().all()
        if not records:
            return []

        hydrated_payloads = await asyncio.gather(
            *(hydrate_edi_data(self.storage, j.storage_uri, j.edi_data) for j in records)
        )
        return [
            self._to_domain_model(record, payload)
            for record, payload in zip(records, hydrated_payloads, strict=True)
        ]
