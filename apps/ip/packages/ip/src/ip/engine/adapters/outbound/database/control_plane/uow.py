"""SQLAlchemy Unit of Work implementation for Integration Platform Control Plane."""

from __future__ import annotations

from ip.engine.ports.outbound.connection_entity_repository_port import (
    ConnectionEntityRepositoryPort,
)
from ip.engine.ports.outbound.connection_policy_repository_port import (
    ConnectionPolicyRepositoryPort,
)
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.engine.ports.outbound.mapping_spec_repository_port import (
    MappingSpecRepositoryPort,
)
from ip.engine.ports.outbound.stitch_repository_port import StitchRepositoryPort
from ip.engine.ports.outbound.stitch_task_config_repository_port import (
    StitchTaskConfigRepositoryPort,
)
from ip.engine.ports.outbound.sync_run_repository_port import SyncRunRepositoryPort
from ip.engine.ports.outbound.transformation_repository_port import (
    TransformationRepositoryPort,
)
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort
from ip.engine.ports.outbound.webhook_endpoint_repository_port import (
    WebhookEndpointRepositoryPort,
)
from sqlalchemy.ext.asyncio import AsyncSession

from database.uow import BaseSqlAlchemyUnitOfWork


class SqlAlchemyIpControlPlaneUnitOfWork(BaseSqlAlchemyUnitOfWork, IpControlPlaneUnitOfWorkPort):
    """Concrete Unit of Work for the Integration Platform Control Plane (global_db, schema 'ip')."""

    connections: ConnectionRepositoryPort
    connection_policies: ConnectionPolicyRepositoryPort
    entities: ConnectionEntityRepositoryPort
    sync_runs: SyncRunRepositoryPort
    transformations: TransformationRepositoryPort
    mapping_specs: MappingSpecRepositoryPort
    stitches: StitchRepositoryPort
    stitch_task_configs: StitchTaskConfigRepositoryPort
    webhook_endpoints: WebhookEndpointRepositoryPort

    def __init__(
        self,
        global_session: AsyncSession,
        *,
        connections: ConnectionRepositoryPort,
        connection_policies: ConnectionPolicyRepositoryPort,
        entities: ConnectionEntityRepositoryPort,
        sync_runs: SyncRunRepositoryPort,
        transformations: TransformationRepositoryPort,
        mapping_specs: MappingSpecRepositoryPort,
        stitches: StitchRepositoryPort,
        stitch_task_configs: StitchTaskConfigRepositoryPort,
        webhook_endpoints: WebhookEndpointRepositoryPort,
    ) -> None:
        super().__init__(global_session)
        self.global_session = global_session
        self.connections = connections
        self.connection_policies = connection_policies
        self.entities = entities
        self.sync_runs = sync_runs
        self.transformations = transformations
        self.mapping_specs = mapping_specs
        self.stitches = stitches
        self.stitch_task_configs = stitch_task_configs
        self.webhook_endpoints = webhook_endpoints


__all__ = ["SqlAlchemyIpControlPlaneUnitOfWork"]
