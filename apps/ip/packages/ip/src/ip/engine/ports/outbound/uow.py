"""Unit of Work outbound ports for Integration Platform Control Plane and Data Plane."""

from __future__ import annotations

import contextlib
from typing import Protocol

from seedwork.uow import UnitOfWorkPort

from ip.engine.domain.exceptions import Result, TenantShardNotFoundError
from ip.engine.ports.outbound.catalog_repository_port import CatalogRepositoryPort
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.engine.ports.outbound.entity_map_repository_port import GlobalEntityMapRepositoryPort
from ip.engine.ports.outbound.inbound_record_repository_port import InboundRecordRepositoryPort
from ip.engine.ports.outbound.normalized_record_repository_port import (
    NormalizedRecordRepositoryPort,
)
from ip.engine.ports.outbound.outbound_record_repository_port import OutboundRecordRepositoryPort
from ip.engine.ports.outbound.replica_record_repository_port import ReplicaRecordRepositoryPort
from ip.engine.ports.outbound.replica_rejection_repository_port import (
    ReplicaRejectionRepositoryPort,
)
from ip.engine.ports.outbound.stream_state_repository_port import StreamStateRepositoryPort
from ip.engine.ports.outbound.sync_run_repository_port import SyncRunRepositoryPort


class IpControlPlaneUnitOfWorkPort(UnitOfWorkPort, Protocol):
    """Unit of Work Port for the Integration Platform Control Plane (global_db, schema 'ip').

    Exposes abstract Control Plane repository interfaces and transaction lifecycle methods.
    """

    connections: ConnectionRepositoryPort
    catalogs: CatalogRepositoryPort
    stream_states: StreamStateRepositoryPort
    sync_runs: SyncRunRepositoryPort


class IpDataPlaneUnitOfWorkPort(UnitOfWorkPort, Protocol):
    """Unit of Work Port for the Integration Platform Data Plane (tenant shards, public schema).

    Exposes abstract Data Plane repository interfaces and transaction lifecycle methods.
    """

    inbound_records: InboundRecordRepositoryPort
    replica_records: ReplicaRecordRepositoryPort
    replica_rejections: ReplicaRejectionRepositoryPort
    normalized_records: NormalizedRecordRepositoryPort
    entity_maps: GlobalEntityMapRepositoryPort
    outbound_records: OutboundRecordRepositoryPort


class IpDataPlaneUnitOfWorkProviderPort(Protocol):
    """Port for resolving a tenant's Data Plane shard and provisioning a scoped IpDataPlaneUnitOfWorkPort."""

    async def resolve_shard_info(
        self, tenant_id: str
    ) -> Result[tuple[str, str], TenantShardNotFoundError]: ...

    def get_data_plane_uow(
        self,
        tenant_id: str,
        shard_id: str,
        shard_dsn: str,
    ) -> contextlib.AbstractAsyncContextManager[IpDataPlaneUnitOfWorkPort]: ...


__all__ = [
    "IpControlPlaneUnitOfWorkPort",
    "IpDataPlaneUnitOfWorkPort",
    "IpDataPlaneUnitOfWorkProviderPort",
]
