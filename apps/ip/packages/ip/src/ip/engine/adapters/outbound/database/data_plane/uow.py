"""SQLAlchemy Unit of Work implementation for Integration Platform Data Plane."""

from __future__ import annotations

from ip.engine.adapters.outbound.database.data_plane.entity_map_repository import (
    SqlAlchemyGlobalEntityMapRepository,
)
from ip.engine.adapters.outbound.database.data_plane.inbound_record_repository import (
    SqlAlchemyInboundRecordRepository,
)
from ip.engine.adapters.outbound.database.data_plane.normalization_ledger_repository import (
    SqlAlchemyNormalizationLedgerRepository,
)
from ip.engine.adapters.outbound.database.data_plane.normalization_rejection_repository import (
    SqlAlchemyNormalizationRejectionRepository,
)
from ip.engine.adapters.outbound.database.data_plane.outbound_record_repository import (
    SqlAlchemyOutboundRecordRepository,
)
from ip.engine.adapters.outbound.database.data_plane.pending_reference_repository import (
    SqlAlchemyPendingReferenceRepository,
)
from ip.engine.adapters.outbound.database.data_plane.replica_record_repository import (
    SqlAlchemyReplicaRecordRepository,
)
from ip.engine.adapters.outbound.database.data_plane.replica_rejection_repository import (
    SqlAlchemyReplicaRejectionRepository,
)
from ip.engine.ports.outbound.entity_map_repository_port import GlobalEntityMapRepositoryPort
from ip.engine.ports.outbound.inbound_record_repository_port import InboundRecordRepositoryPort
from ip.engine.ports.outbound.normalization_ledger_repository_port import (
    NormalizationLedgerRepositoryPort,
)
from ip.engine.ports.outbound.normalization_rejection_repository_port import (
    NormalizationRejectionRepositoryPort,
)
from ip.engine.ports.outbound.outbound_record_repository_port import OutboundRecordRepositoryPort
from ip.engine.ports.outbound.pending_reference_repository_port import (
    PendingReferenceRepositoryPort,
)
from ip.engine.ports.outbound.replica_record_repository_port import ReplicaRecordRepositoryPort
from ip.engine.ports.outbound.replica_rejection_repository_port import (
    ReplicaRejectionRepositoryPort,
)
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkPort
from sqlalchemy.ext.asyncio import AsyncSession

from database.uow import BaseSqlAlchemyUnitOfWork


class SqlAlchemyIpDataPlaneUnitOfWork(BaseSqlAlchemyUnitOfWork, IpDataPlaneUnitOfWorkPort):
    """Concrete Unit of Work for the Integration Platform Data Plane (tenant shards)."""

    inbound_records: InboundRecordRepositoryPort
    replica_records: ReplicaRecordRepositoryPort
    replica_rejections: ReplicaRejectionRepositoryPort
    entity_maps: GlobalEntityMapRepositoryPort
    outbound_records: OutboundRecordRepositoryPort
    normalization_ledger: NormalizationLedgerRepositoryPort
    normalization_rejections: NormalizationRejectionRepositoryPort
    pending_references: PendingReferenceRepositoryPort

    def __init__(self, tenant_session: AsyncSession) -> None:
        super().__init__(tenant_session)
        self.tenant_session = tenant_session
        self.inbound_records = SqlAlchemyInboundRecordRepository(tenant_session)
        self.replica_records = SqlAlchemyReplicaRecordRepository(tenant_session)
        self.replica_rejections = SqlAlchemyReplicaRejectionRepository(tenant_session)
        self.entity_maps = SqlAlchemyGlobalEntityMapRepository(tenant_session)
        self.outbound_records = SqlAlchemyOutboundRecordRepository(tenant_session)
        self.normalization_ledger = SqlAlchemyNormalizationLedgerRepository(tenant_session)
        self.normalization_rejections = SqlAlchemyNormalizationRejectionRepository(tenant_session)
        self.pending_references = SqlAlchemyPendingReferenceRepository(tenant_session)


__all__ = ["SqlAlchemyIpDataPlaneUnitOfWork"]
