"""SQLAlchemy Unit of Work implementation for Integration Platform Data Plane."""

from __future__ import annotations

from collections.abc import Mapping

from ip.engine.adapters.outbound.database.data_plane.trace_specs import (
    build_ip_outbox_record_from_envelope,
)
from ip.engine.adapters.outbound.database.models.data_plane import (
    IpDataPlaneOutboxRecord,
    IpProcessedEventModel,
)
from ip.engine.ports.outbound.entity_map_repository_port import GlobalEntityMapRepositoryPort
from ip.engine.ports.outbound.inbound_record_repository_port import InboundRecordRepositoryPort
from ip.engine.ports.outbound.normalization_ledger_repository_port import (
    NormalizationLedgerRepositoryPort,
)
from ip.engine.ports.outbound.normalization_rejection_repository_port import (
    NormalizationRejectionRepositoryPort,
)
from ip.engine.ports.outbound.normalized_record_repository_port import (
    NormalizedRecordRepositoryPort,
)
from ip.engine.ports.outbound.outbound_record_repository_port import OutboundRecordRepositoryPort
from ip.engine.ports.outbound.pending_reference_repository_port import (
    PendingReferenceRepositoryPort,
)
from ip.engine.ports.outbound.replica_record_repository_port import ReplicaRecordRepositoryPort
from ip.engine.ports.outbound.replica_rejection_repository_port import (
    ReplicaRejectionRepositoryPort,
)
from ip.engine.ports.outbound.uow import (
    DomainRepositoryKey,
    IpDataPlaneUnitOfWorkPort,
    TDomainRepo,
)
from seedwork.events import EventEnvelope
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from strace.ports import TraceRepositoryPort

from database.uow import BaseSqlAlchemyUnitOfWork


class SqlAlchemyIpDataPlaneUnitOfWork(BaseSqlAlchemyUnitOfWork, IpDataPlaneUnitOfWorkPort):
    """Concrete Unit of Work for the Integration Platform Data Plane (tenant shards)."""

    inbound_records: InboundRecordRepositoryPort
    replica_records: ReplicaRecordRepositoryPort
    replica_rejections: ReplicaRejectionRepositoryPort
    normalized_records: NormalizedRecordRepositoryPort
    entity_maps: GlobalEntityMapRepositoryPort
    outbound_records: OutboundRecordRepositoryPort
    normalization_ledger: NormalizationLedgerRepositoryPort
    normalization_rejections: NormalizationRejectionRepositoryPort
    pending_references: PendingReferenceRepositoryPort
    traces: TraceRepositoryPort

    def __init__(
        self,
        tenant_session: AsyncSession,
        *,
        inbound_records: InboundRecordRepositoryPort,
        replica_records: ReplicaRecordRepositoryPort,
        replica_rejections: ReplicaRejectionRepositoryPort,
        normalized_records: NormalizedRecordRepositoryPort,
        entity_maps: GlobalEntityMapRepositoryPort,
        outbound_records: OutboundRecordRepositoryPort,
        normalization_ledger: NormalizationLedgerRepositoryPort,
        normalization_rejections: NormalizationRejectionRepositoryPort,
        pending_references: PendingReferenceRepositoryPort,
        traces: TraceRepositoryPort,
        domain_repositories: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(tenant_session)
        self.tenant_session = tenant_session
        self.inbound_records = inbound_records
        self.replica_records = replica_records
        self.replica_rejections = replica_rejections
        self.normalized_records = normalized_records
        self.entity_maps = entity_maps
        self.outbound_records = outbound_records
        self.normalization_ledger = normalization_ledger
        self.normalization_rejections = normalization_rejections
        self.pending_references = pending_references
        self.traces = traces
        self._domain_repositories: dict[str, object] = (
            dict(domain_repositories) if domain_repositories is not None else {}
        )

    def resolve_domain_repository(
        self, key: DomainRepositoryKey[TDomainRepo]
    ) -> TDomainRepo | None:
        repo = self._domain_repositories.get(key.name)
        if repo is None:
            return None
        return key.narrow(repo)

    async def record_idempotency(self, tenant_id: str, idempotency_key: str) -> bool:
        """Atomically claims an inbound event idempotency key in ip_processed_events."""
        stmt = (
            pg_insert(IpProcessedEventModel)
            .values(
                idempotency_key=idempotency_key,
                tenant_id=tenant_id,
            )
            .on_conflict_do_nothing(index_elements=[IpProcessedEventModel.idempotency_key])
            .returning(IpProcessedEventModel.idempotency_key)
        )
        result = await self.tenant_session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def release_idempotency(self, tenant_id: str, idempotency_key: str) -> None:
        """Releases a previously claimed idempotency key when a chunk fails transiently (NACK)."""
        stmt = delete(IpProcessedEventModel).where(
            IpProcessedEventModel.idempotency_key == idempotency_key,
            IpProcessedEventModel.tenant_id == tenant_id,
        )
        await self.tenant_session.execute(stmt)

    async def stage_outbox_envelope(self, envelope: EventEnvelope) -> None:
        """Idempotently stages an EventEnvelope into `public.ip_outbox` within the current shard transaction."""
        record = build_ip_outbox_record_from_envelope(envelope)
        stmt = (
            pg_insert(IpDataPlaneOutboxRecord)
            .values(
                id=record.id,
                tenant_id=record.tenant_id,
                idempotency_key=record.idempotency_key,
                event_type=record.event_type,
                trace_id=record.trace_id,
                correlation_id=record.correlation_id,
                lane=record.lane,
                payload=record.payload,
                status=record.status,
                attempts=record.attempts,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            .on_conflict_do_nothing(index_elements=[IpDataPlaneOutboxRecord.idempotency_key])
        )
        await self.tenant_session.execute(stmt)


__all__ = ["SqlAlchemyIpDataPlaneUnitOfWork"]
