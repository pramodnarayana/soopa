"""SQLAlchemy repository adapter for Layer 2 ReplicaRecord aggregates."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from ip.engine.adapters.outbound.database.base_repository import TenantSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.data_plane import ReplicaRecordModel
from ip.engine.domain.enums import CursorKind, MergeOutcome
from ip.engine.domain.models.replica_record import ReplicaMergePolicy, ReplicaRecord
from ip.engine.ports.outbound.replica_record_repository_port import (
    MergeResult,
    ReplicaMergeCandidate,
    ReplicaRecordRepositoryPort,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyReplicaRecordRepository(TenantSqlAlchemyRepository, ReplicaRecordRepositoryPort):
    """Repository persisting and retrieving ReplicaRecord aggregates with transactional outbox draining."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_domain_model(orm: ReplicaRecordModel) -> ReplicaRecord:
        return ReplicaRecord(
            id=orm.id,
            tenant_id=orm.tenant_id,
            trace_id=orm.trace_id,
            correlation_id=orm.correlation_id,
            connection_id=orm.connection_id,
            stream=orm.stream,
            record_key=orm.record_key,
            primary_key_values=tuple(orm.primary_key_values or ()),
            cursor_value=orm.cursor_value,
            cursor_kind=orm.cursor_kind,
            data=dict(orm.data),
            data_hash=orm.data_hash,
            version=orm.version,
            generation_id=orm.generation_id,
            last_seen_generation=orm.last_seen_generation,
            first_seen_at=orm.first_seen_at,
            extracted_at=orm.extracted_at,
            updated_at=orm.updated_at,
            deleted_at=orm.deleted_at,
            source_inbound_record_id=orm.source_inbound_record_id,
        )

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
        orm.updated_at = domain.updated_at
        orm.deleted_at = domain.deleted_at
        orm.source_inbound_record_id = domain.source_inbound_record_id

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

    async def get_by_entity(
        self,
        tenant_id: str,
        connection_id: str,
        entity_type: str,
        entity_id: str,
    ) -> ReplicaRecord | None:
        """Backward-compatible lookup mapping entity_type -> stream and entity_id -> record_key."""
        return await self.get_by_key(
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream=entity_type,
            record_key=entity_id,
        )

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

    def _handle_insert(
        self, c: ReplicaMergeCandidate, now: datetime
    ) -> tuple[ReplicaRecordModel, MergeResult]:
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
        if c.is_deleted:
            domain_record.tombstone(
                trace_id=c.trace_id,
                correlation_id=c.correlation_id,
            )

        orm = ReplicaRecordModel(
            id=domain_record.id,
            tenant_id=domain_record.tenant_id,
            connection_id=domain_record.connection_id,
            stream=domain_record.stream,
            record_key=domain_record.record_key,
            primary_key_values=list(domain_record.primary_key_values),
            cursor_value=domain_record.cursor_value,
            cursor_kind=domain_record.cursor_kind,
            data=dict(domain_record.data),
            data_hash=domain_record.data_hash,
            version=domain_record.version,
            generation_id=domain_record.generation_id,
            last_seen_generation=domain_record.last_seen_generation,
            first_seen_at=domain_record.first_seen_at,
            extracted_at=domain_record.extracted_at,
            updated_at=domain_record.updated_at,
            deleted_at=domain_record.deleted_at,
            source_inbound_record_id=domain_record.source_inbound_record_id,
            trace_id=domain_record.trace_id,
            correlation_id=domain_record.correlation_id,
        )
        self._session.add(orm)
        self._drain_trace_events(domain_record)
        self._drain_events(domain_record, default_tenant_id=c.tenant_id)

        result = MergeResult(
            record_id=domain_record.id,
            stream=c.stream,
            record_key=c.record_key,
            outcome=MergeOutcome.INSERT,
            version=domain_record.version,
            data_hash=c.data_hash,
        )
        return orm, result

    def _handle_update(
        self,
        existing_orm: ReplicaRecordModel,
        existing_domain: ReplicaRecord,
        c: ReplicaMergeCandidate,
        now: datetime,
    ) -> MergeResult:
        existing_domain.update_snapshot(
            new_data=c.data,
            trace_id=c.trace_id,
            correlation_id=c.correlation_id,
            cursor_value=str(c.cursor_value) if c.cursor_value is not None else None,
            generation_id=c.generation_id,
        )
        self._update_record_from_domain(existing_orm, existing_domain)
        self._drain_trace_events(existing_domain)
        self._drain_events(existing_domain, default_tenant_id=c.tenant_id)

        return MergeResult(
            record_id=existing_orm.id,
            stream=c.stream,
            record_key=c.record_key,
            outcome=MergeOutcome.UPDATE,
            version=existing_orm.version,
            data_hash=c.data_hash,
        )

    def _handle_tombstone(
        self,
        existing_orm: ReplicaRecordModel,
        existing_domain: ReplicaRecord,
        c: ReplicaMergeCandidate,
        now: datetime,
    ) -> MergeResult:
        existing_domain.tombstone(
            trace_id=c.trace_id,
            correlation_id=c.correlation_id,
        )
        self._update_record_from_domain(existing_orm, existing_domain)
        self._drain_trace_events(existing_domain)
        self._drain_events(existing_domain, default_tenant_id=c.tenant_id)

        return MergeResult(
            record_id=existing_orm.id,
            stream=c.stream,
            record_key=c.record_key,
            outcome=MergeOutcome.TOMBSTONE,
            version=existing_orm.version,
            data_hash=existing_orm.data_hash,
        )

    @staticmethod
    def _handle_noop(
        existing_orm: ReplicaRecordModel, c: ReplicaMergeCandidate, now: datetime
    ) -> MergeResult:
        existing_orm.last_seen_generation = c.generation_id
        existing_orm.extracted_at = now
        return MergeResult(
            record_id=existing_orm.id,
            stream=c.stream,
            record_key=c.record_key,
            outcome=MergeOutcome.NOOP,
            version=existing_orm.version,
            data_hash=existing_orm.data_hash,
        )

    @staticmethod
    def _handle_stale(existing_orm: ReplicaRecordModel, c: ReplicaMergeCandidate) -> MergeResult:
        return MergeResult(
            record_id=existing_orm.id,
            stream=c.stream,
            record_key=c.record_key,
            outcome=MergeOutcome.STALE,
            version=existing_orm.version,
            data_hash=existing_orm.data_hash,
        )

    async def _fetch_existing_map(
        self, candidates: Sequence[ReplicaMergeCandidate]
    ) -> dict[tuple[str, str], ReplicaRecordModel]:
        keys_by_stream: dict[str, list[str]] = {}
        for c in candidates:
            keys_by_stream.setdefault(c.stream, []).append(c.record_key)

        tenant_id = candidates[0].tenant_id
        connection_id = candidates[0].connection_id

        existing_map: dict[tuple[str, str], ReplicaRecordModel] = {}
        chunk_size = 500
        for stream_name, keys in keys_by_stream.items():
            for i in range(0, len(keys), chunk_size):
                key_chunk = keys[i : i + chunk_size]
                stmt = select(ReplicaRecordModel).where(
                    ReplicaRecordModel.tenant_id == tenant_id,
                    ReplicaRecordModel.connection_id == connection_id,
                    ReplicaRecordModel.stream == stream_name,
                    ReplicaRecordModel.record_key.in_(key_chunk),
                )
                res = await self._session.execute(stmt)
                for row in res.scalars():
                    existing_map[(row.stream, row.record_key)] = row
        return existing_map

    def _process_candidate(
        self,
        c: ReplicaMergeCandidate,
        existing_map: dict[tuple[str, str], ReplicaRecordModel],
        now: datetime,
    ) -> MergeResult | None:
        existing_orm = existing_map.get((c.stream, c.record_key))
        existing_domain = self._to_domain_model(existing_orm) if existing_orm else None

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
            new_orm, res_dto = self._handle_insert(c, now)
            existing_map[(c.stream, c.record_key)] = new_orm
            return res_dto
        if (
            outcome == MergeOutcome.UPDATE
            and existing_orm is not None
            and existing_domain is not None
        ):
            return self._handle_update(existing_orm, existing_domain, c, now)
        if (
            outcome == MergeOutcome.TOMBSTONE
            and existing_orm is not None
            and existing_domain is not None
        ):
            return self._handle_tombstone(existing_orm, existing_domain, c, now)
        if outcome == MergeOutcome.NOOP and existing_orm is not None:
            return self._handle_noop(existing_orm, c, now)
        if outcome == MergeOutcome.STALE and existing_orm is not None:
            return self._handle_stale(existing_orm, c)
        return None

    async def merge_batch(
        self,
        candidates: Sequence[ReplicaMergeCandidate],
    ) -> list[MergeResult]:
        """Merges a batch of candidate records, updating existing records or creating new ones."""
        if not candidates:
            return []

        now = datetime.now(UTC)
        existing_map = await self._fetch_existing_map(candidates)

        results: list[MergeResult] = []
        for c in candidates:
            res = self._process_candidate(c, existing_map, now)
            if res is not None:
                results.append(res)

        await self._session.flush()
        return results

    async def tombstone_unseen_generations(
        self,
        tenant_id: str,
        connection_id: str,
        stream: str,
        current_generation: int,
        limit: int = 500,
    ) -> int:
        """Tombstones rows where last_seen_generation < current_generation in bounded chunks."""
        # Find candidate IDs to tombstone
        stmt = (
            select(ReplicaRecordModel.id)
            .where(
                ReplicaRecordModel.tenant_id == tenant_id,
                ReplicaRecordModel.connection_id == connection_id,
                ReplicaRecordModel.stream == stream,
                ReplicaRecordModel.last_seen_generation < current_generation,
                ReplicaRecordModel.deleted_at.is_(None),
            )
            .limit(limit)
        )
        res = await self._session.execute(stmt)
        candidate_ids = res.scalars().all()
        if not candidate_ids:
            return 0

        now = datetime.now(UTC)
        update_stmt = (
            update(ReplicaRecordModel)
            .where(ReplicaRecordModel.id.in_(candidate_ids))
            .values(
                deleted_at=now,
                version=ReplicaRecordModel.version + 1,
                updated_at=now,
            )
        )
        await self._session.execute(update_stmt)
        await self._session.flush()
        return len(candidate_ids)
