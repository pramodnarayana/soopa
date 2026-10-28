"""SQLAlchemy repository adapter for Layer 2 ReplicaRecord aggregates."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TypedDict

import structlog
from ip.engine.adapters.outbound.database.base_repository import TenantSqlAlchemyRepository
from ip.engine.adapters.outbound.database.data_plane.mappers import replica_record_to_domain
from ip.engine.adapters.outbound.database.models.data_plane import ReplicaRecordModel
from ip.engine.domain.enums import CursorKind, MergeOutcome
from ip.engine.domain.events import ReplicaRecordChangedEvent
from ip.engine.domain.models.replica_record import ReplicaMergePolicy, ReplicaRecord
from ip.engine.ports.outbound.replica_record_repository_port import (
    MergeResult,
    ReplicaMergeCandidate,
    ReplicaRecordRepositoryPort,
)
from seedwork.domain.types import JsonDict
from seedwork.events import EventProcessingLane
from seedwork.id_registry import DomainIdPrefix
from seedwork.utils import generate_id
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class ReplicaRecordRowDict(TypedDict):
    """Strongly-typed row dictionary for PostgreSQL bulk upsert."""

    id: str
    tenant_id: str
    connection_id: str
    stream: str
    record_key: str
    primary_key_values: list[str | int | float | bool | None]
    cursor_value: str | None
    cursor_kind: str | None
    data: JsonDict
    data_hash: str
    version: int
    generation_id: int
    last_seen_generation: int
    first_seen_at: datetime
    extracted_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    source_inbound_record_id: str | None
    trace_id: str
    correlation_id: str | None


class SqlAlchemyReplicaRecordRepository(TenantSqlAlchemyRepository, ReplicaRecordRepositoryPort):
    """Repository persisting and retrieving ReplicaRecord aggregates with transactional outbox draining."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_domain_model(orm: ReplicaRecordModel) -> ReplicaRecord:
        return replica_record_to_domain(orm)

    @staticmethod
    def _update_record_from_domain(orm: ReplicaRecordModel, domain: ReplicaRecord) -> None:
        orm.stream = domain.stream
        orm.record_key = domain.record_key
        orm.primary_key_values = list(domain.primary_key_values)
        orm.cursor_value = domain.cursor_value
        orm.cursor_kind = domain.cursor_kind
        orm.data = dict(domain.data)
        orm.data_hash = domain.data_hash
        orm.trace_id = domain.trace_id
        orm.correlation_id = domain.correlation_id
        orm.version = domain.version
        orm.generation_id = domain.generation_id
        orm.last_seen_generation = domain.last_seen_generation
        orm.extracted_at = domain.extracted_at
        orm.updated_at = domain.updated_at
        orm.deleted_at = domain.deleted_at
        orm.source_inbound_record_id = domain.source_inbound_record_id

    @staticmethod
    def _domain_to_row_dict(domain: ReplicaRecord) -> ReplicaRecordRowDict:
        return {
            "id": domain.id,
            "tenant_id": domain.tenant_id,
            "connection_id": domain.connection_id,
            "stream": domain.stream,
            "record_key": domain.record_key,
            "primary_key_values": list(domain.primary_key_values),
            "cursor_value": domain.cursor_value,
            "cursor_kind": domain.cursor_kind,
            "data": dict(domain.data),
            "data_hash": domain.data_hash,
            "version": domain.version,
            "generation_id": domain.generation_id,
            "last_seen_generation": domain.last_seen_generation,
            "first_seen_at": domain.first_seen_at,
            "extracted_at": domain.extracted_at,
            "updated_at": domain.updated_at,
            "deleted_at": domain.deleted_at,
            "source_inbound_record_id": domain.source_inbound_record_id,
            "trace_id": domain.trace_id,
            "correlation_id": domain.correlation_id,
        }

    async def get_by_id(
        self,
        tenant_id: str,
        record_id: str,
    ) -> ReplicaRecord | None:
        stmt = select(ReplicaRecordModel).where(
            ReplicaRecordModel.tenant_id == tenant_id,
            ReplicaRecordModel.id == record_id,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return self._to_domain_model(orm)

    async def get_by_key(
        self,
        tenant_id: str,
        connection_id: str,
        stream: str,
        record_key: str,
    ) -> ReplicaRecord | None:
        stmt = select(ReplicaRecordModel).where(
            ReplicaRecordModel.tenant_id == tenant_id,
            ReplicaRecordModel.connection_id == connection_id,
            ReplicaRecordModel.stream == stream,
            ReplicaRecordModel.record_key == record_key,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return self._to_domain_model(orm)

    async def save(self, record: ReplicaRecord) -> None:
        stmt = select(ReplicaRecordModel).where(ReplicaRecordModel.id == record.id)
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is None:
            orm = ReplicaRecordModel(
                id=record.id,
                tenant_id=record.tenant_id,
                trace_id=record.trace_id,
                correlation_id=record.correlation_id,
                connection_id=record.connection_id,
                stream=record.stream,
                record_key=record.record_key,
                primary_key_values=list(record.primary_key_values),
                cursor_value=record.cursor_value,
                cursor_kind=record.cursor_kind,
                data=dict(record.data),
                data_hash=record.data_hash,
                version=record.version,
                generation_id=record.generation_id,
                last_seen_generation=record.last_seen_generation,
                first_seen_at=record.first_seen_at,
                extracted_at=record.extracted_at,
                updated_at=record.updated_at,
                deleted_at=record.deleted_at,
                source_inbound_record_id=record.source_inbound_record_id,
            )
            self._session.add(orm)
        else:
            self._update_record_from_domain(existing, record)

        self._drain_trace_events(record)
        self._drain_events(record, default_tenant_id=record.tenant_id)
        await self._session.flush()

    async def _fetch_existing_domain_map(
        self, candidates: Sequence[ReplicaMergeCandidate]
    ) -> dict[tuple[str, str], ReplicaRecord]:
        keys_by_stream: dict[str, list[str]] = {}
        for c in candidates:
            keys_by_stream.setdefault(c.stream, []).append(c.record_key)

        tenant_id = candidates[0].tenant_id
        connection_id = candidates[0].connection_id

        existing_map: dict[tuple[str, str], ReplicaRecord] = {}
        chunk_size = 500
        for stream_name, keys in keys_by_stream.items():
            unique_keys = list(dict.fromkeys(keys))
            for i in range(0, len(unique_keys), chunk_size):
                key_chunk = unique_keys[i : i + chunk_size]
                stmt = (
                    select(ReplicaRecordModel)
                    .where(
                        ReplicaRecordModel.tenant_id == tenant_id,
                        ReplicaRecordModel.connection_id == connection_id,
                        ReplicaRecordModel.stream == stream_name,
                        ReplicaRecordModel.record_key.in_(key_chunk),
                    )
                    .with_for_update()
                )
                res = await self._session.execute(stmt)
                for row in res.scalars():
                    existing_map[(row.stream, row.record_key)] = self._to_domain_model(row)
                    self._session.expunge(row)
        return existing_map

    def _evaluate_candidate(
        self,
        c: ReplicaMergeCandidate,
        existing_map: dict[tuple[str, str], ReplicaRecord],
        upsert_rows: dict[tuple[str, str], ReplicaRecordRowDict],
        changed_aggregates: dict[tuple[str, str], ReplicaRecord],
        now: datetime,
    ) -> MergeResult:
        map_key = (c.stream, c.record_key)
        existing_domain = existing_map.get(map_key)

        cursor_kind = (
            CursorKind(c.cursor_kind)
            if c.cursor_kind is not None and c.cursor_kind in CursorKind.__members__.values()
            else CursorKind.STRING
        )
        outcome = ReplicaMergePolicy.evaluate(
            existing=existing_domain,
            incoming_data_hash=c.data_hash,
            incoming_cursor=c.cursor_value,
            cursor_kind=cursor_kind,
            is_deleted=c.is_deleted,
        )

        if outcome == MergeOutcome.INSERT:
            domain_record = ReplicaRecord.create(
                tenant_id=c.tenant_id,
                connection_id=c.connection_id,
                stream=c.stream,
                record_key=c.record_key,
                primary_key_values=c.primary_key_values,
                cursor_value=str(c.cursor_value) if c.cursor_value is not None else None,
                cursor_kind=c.cursor_kind,
                data=c.data,
                generation_id=c.generation_id,
                source_inbound_record_id=c.source_inbound_record_id,
                trace_id=c.trace_id,
                correlation_id=c.correlation_id,
            )
            existing_map[map_key] = domain_record
            upsert_rows[map_key] = self._domain_to_row_dict(domain_record)
            changed_aggregates[map_key] = domain_record
            return MergeResult(
                record_id=domain_record.id,
                stream=c.stream,
                record_key=c.record_key,
                outcome=MergeOutcome.INSERT,
                version=domain_record.version,
                data_hash=c.data_hash,
            )

        if outcome == MergeOutcome.TOMBSTONE:
            if existing_domain is None:
                domain_record = ReplicaRecord.create_tombstone(
                    tenant_id=c.tenant_id,
                    connection_id=c.connection_id,
                    stream=c.stream,
                    record_key=c.record_key,
                    primary_key_values=c.primary_key_values,
                    cursor_value=str(c.cursor_value) if c.cursor_value is not None else None,
                    cursor_kind=c.cursor_kind,
                    data=c.data,
                    generation_id=c.generation_id,
                    source_inbound_record_id=c.source_inbound_record_id,
                    trace_id=c.trace_id,
                    correlation_id=c.correlation_id,
                )
                existing_map[map_key] = domain_record
                upsert_rows[map_key] = self._domain_to_row_dict(domain_record)
                changed_aggregates[map_key] = domain_record
                return MergeResult(
                    record_id=domain_record.id,
                    stream=c.stream,
                    record_key=c.record_key,
                    outcome=MergeOutcome.TOMBSTONE,
                    version=domain_record.version,
                    data_hash=c.data_hash,
                )

            existing_domain.tombstone(
                trace_id=c.trace_id,
                correlation_id=c.correlation_id,
                generation_id=c.generation_id,
                source_inbound_record_id=c.source_inbound_record_id,
            )
            upsert_rows[map_key] = self._domain_to_row_dict(existing_domain)
            changed_aggregates[map_key] = existing_domain
            return MergeResult(
                record_id=existing_domain.id,
                stream=c.stream,
                record_key=c.record_key,
                outcome=MergeOutcome.TOMBSTONE,
                version=existing_domain.version,
                data_hash=existing_domain.data_hash,
            )

        assert existing_domain is not None

        if outcome == MergeOutcome.UPDATE:
            existing_domain.update_snapshot(
                new_data=c.data,
                trace_id=c.trace_id,
                correlation_id=c.correlation_id,
                cursor_value=str(c.cursor_value) if c.cursor_value is not None else None,
                generation_id=c.generation_id,
                source_inbound_record_id=c.source_inbound_record_id,
            )
            upsert_rows[map_key] = self._domain_to_row_dict(existing_domain)
            changed_aggregates[map_key] = existing_domain
            return MergeResult(
                record_id=existing_domain.id,
                stream=c.stream,
                record_key=c.record_key,
                outcome=MergeOutcome.UPDATE,
                version=existing_domain.version,
                data_hash=c.data_hash,
            )

        if outcome == MergeOutcome.NOOP:
            existing_domain.last_seen_generation = c.generation_id
            existing_domain.extracted_at = now
            upsert_rows[map_key] = self._domain_to_row_dict(existing_domain)
            return MergeResult(
                record_id=existing_domain.id,
                stream=c.stream,
                record_key=c.record_key,
                outcome=MergeOutcome.NOOP,
                version=existing_domain.version,
                data_hash=existing_domain.data_hash,
            )

        logger.info(
            "replica_record_stale_cursor_ignored",
            tenant_id=c.tenant_id,
            connection_id=c.connection_id,
            stream=c.stream,
            record_key=c.record_key,
            incoming_cursor=c.cursor_value,
            existing_cursor=existing_domain.cursor_value,
        )
        return MergeResult(
            record_id=existing_domain.id,
            stream=c.stream,
            record_key=c.record_key,
            outcome=MergeOutcome.STALE,
            version=existing_domain.version,
            data_hash=existing_domain.data_hash,
        )

    async def merge_batch(
        self,
        candidates: Sequence[ReplicaMergeCandidate],
    ) -> list[MergeResult]:
        """Merges a batch of candidate records using one atomic PostgreSQL INSERT ... ON CONFLICT DO UPDATE."""
        if not candidates:
            return []

        now = datetime.now(UTC)
        existing_map = await self._fetch_existing_domain_map(candidates)
        upsert_rows: dict[tuple[str, str], ReplicaRecordRowDict] = {}
        changed_aggregates: dict[tuple[str, str], ReplicaRecord] = {}

        results: list[MergeResult] = []
        for c in candidates:
            res = self._evaluate_candidate(
                c=c,
                existing_map=existing_map,
                upsert_rows=upsert_rows,
                changed_aggregates=changed_aggregates,
                now=now,
            )
            results.append(res)

        if upsert_rows:
            insert_stmt = pg_insert(ReplicaRecordModel).values(list(upsert_rows.values()))
            upsert_stmt = insert_stmt.on_conflict_do_update(
                constraint="uq_ip_replica_record_identity",
                set_={
                    "primary_key_values": insert_stmt.excluded.primary_key_values,
                    "cursor_value": insert_stmt.excluded.cursor_value,
                    "cursor_kind": insert_stmt.excluded.cursor_kind,
                    "data": insert_stmt.excluded.data,
                    "data_hash": insert_stmt.excluded.data_hash,
                    "version": insert_stmt.excluded.version,
                    "last_seen_generation": insert_stmt.excluded.last_seen_generation,
                    "extracted_at": insert_stmt.excluded.extracted_at,
                    "updated_at": insert_stmt.excluded.updated_at,
                    "deleted_at": insert_stmt.excluded.deleted_at,
                    "source_inbound_record_id": insert_stmt.excluded.source_inbound_record_id,
                    "trace_id": insert_stmt.excluded.trace_id,
                    "correlation_id": insert_stmt.excluded.correlation_id,
                },
            )
            await self._session.execute(upsert_stmt)

        changed_list = list(changed_aggregates.values())
        for agg in changed_list:
            self._drain_trace_events(agg)

        if len(changed_list) == 1:
            self._drain_events(changed_list[0], default_tenant_id=changed_list[0].tenant_id)
        elif len(changed_list) > 1:
            for agg in changed_list:
                agg.clear_domain_events()
            chunk_size = 250
            for idx in range(0, len(changed_list), chunk_size):
                chunk_aggs = changed_list[idx : idx + chunk_size]
                first = chunk_aggs[0]
                first.add_domain_event(
                    ReplicaRecordChangedEvent(
                        record_id=first.id,
                        record_ids=tuple(a.id for a in chunk_aggs),
                        tenant_id=first.tenant_id,
                        connection_id=first.connection_id,
                        stream=first.stream,
                        record_key=first.record_key,
                        outcome="BATCH_UPSERT",
                        version=first.version,
                        data_hash=first.data_hash,
                        trace_id=first.trace_id,
                        correlation_id=first.correlation_id,
                        lane=EventProcessingLane.BULK,
                    )
                )
                self._drain_events(first, default_tenant_id=first.tenant_id)

        await self._session.flush()
        return results

    async def tombstone_unseen_generations(
        self,
        tenant_id: str,
        connection_id: str,
        stream: str,
        current_generation: int,
        limit: int = 500,
        trace_id: str = "",
    ) -> int:
        """Tombstones rows where last_seen_generation < current_generation in bounded chunks, emitting outbox events."""
        stmt = (
            select(ReplicaRecordModel)
            .where(
                ReplicaRecordModel.tenant_id == tenant_id,
                ReplicaRecordModel.connection_id == connection_id,
                ReplicaRecordModel.stream == stream,
                ReplicaRecordModel.last_seen_generation < current_generation,
                ReplicaRecordModel.deleted_at.is_(None),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        res = await self._session.execute(stmt)
        rows = res.scalars().all()
        if not rows:
            return 0

        actual_trace_id = trace_id or generate_id(DomainIdPrefix.IP_TRACE.value)
        for orm in rows:
            domain_rec = self._to_domain_model(orm)
            domain_rec.tombstone(
                trace_id=actual_trace_id,
                correlation_id=orm.correlation_id,
            )
            self._update_record_from_domain(orm, domain_rec)
            self._drain_trace_events(domain_rec)
            self._drain_events(domain_rec, default_tenant_id=tenant_id)

        await self._session.flush()
        return len(rows)

    async def list_by_stream_chunk(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        stream: str,
        after_id: str | None = None,
        limit: int = 100,
    ) -> list[ReplicaRecord]:
        """Retrieves a deterministic keyset-paginated chunk of replica records for a stream."""
        stmt = select(ReplicaRecordModel).where(
            ReplicaRecordModel.tenant_id == tenant_id,
            ReplicaRecordModel.connection_id == connection_id,
            ReplicaRecordModel.stream == stream,
        )
        if after_id is not None:
            stmt = stmt.where(ReplicaRecordModel.id > after_id)
        stmt = stmt.order_by(ReplicaRecordModel.id.asc()).limit(limit)
        res = await self._session.execute(stmt)
        return [self._to_domain_model(orm) for orm in res.scalars().all()]

    async def get_by_trace_id(
        self,
        trace_id: str,
        tenant_id: str,
    ) -> Sequence[ReplicaRecord]:
        stmt = (
            select(ReplicaRecordModel)
            .where(
                ReplicaRecordModel.trace_id == trace_id,
                ReplicaRecordModel.tenant_id == tenant_id,
            )
            .order_by(ReplicaRecordModel.updated_at.asc())
        )
        res = await self._session.execute(stmt)
        return [self._to_domain_model(orm) for orm in res.scalars().all()]
