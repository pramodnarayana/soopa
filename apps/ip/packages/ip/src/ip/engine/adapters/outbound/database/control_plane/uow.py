"""SQLAlchemy Unit of Work implementation for Integration Platform Control Plane."""

from __future__ import annotations

from ip.engine.adapters.outbound.database.control_plane.catalog_repository import (
    SqlAlchemyCatalogRepository,
)
from ip.engine.adapters.outbound.database.control_plane.connection_repository import (
    SqlAlchemyConnectionRepository,
)
from ip.engine.adapters.outbound.database.control_plane.stitch_repository import (
    SqlAlchemyStitchRepository,
)
from ip.engine.adapters.outbound.database.control_plane.stream_state_repository import (
    SqlAlchemyStreamStateRepository,
)
from ip.engine.adapters.outbound.database.control_plane.sync_run_repository import (
    SqlAlchemySyncRunRepository,
)
from ip.engine.adapters.outbound.database.control_plane.transformation_repository import (
    SqlAlchemyTransformationRepository,
)
from ip.engine.ports.outbound.catalog_repository_port import CatalogRepositoryPort
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.engine.ports.outbound.stitch_repository_port import StitchRepositoryPort
from ip.engine.ports.outbound.stream_state_repository_port import StreamStateRepositoryPort
from ip.engine.ports.outbound.sync_run_repository_port import SyncRunRepositoryPort
from ip.engine.ports.outbound.transformation_repository_port import (
    TransformationRepositoryPort,
)
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort
from sqlalchemy.ext.asyncio import AsyncSession

from database.uow import BaseSqlAlchemyUnitOfWork


class SqlAlchemyIpControlPlaneUnitOfWork(BaseSqlAlchemyUnitOfWork, IpControlPlaneUnitOfWorkPort):
    """Concrete Unit of Work for the Integration Platform Control Plane (global_db, schema 'ip')."""

    connections: ConnectionRepositoryPort
    catalogs: CatalogRepositoryPort
    stream_states: StreamStateRepositoryPort
    sync_runs: SyncRunRepositoryPort
    transformations: TransformationRepositoryPort
    stitches: StitchRepositoryPort

    def __init__(self, global_session: AsyncSession) -> None:
        super().__init__(global_session)
        self.global_session = global_session
        self.connections = SqlAlchemyConnectionRepository(global_session)
        self.catalogs = SqlAlchemyCatalogRepository(global_session)
        self.stream_states = SqlAlchemyStreamStateRepository(global_session)
        self.sync_runs = SqlAlchemySyncRunRepository(global_session)
        self.transformations = SqlAlchemyTransformationRepository(global_session)
        self.stitches = SqlAlchemyStitchRepository(global_session)


__all__ = ["SqlAlchemyIpControlPlaneUnitOfWork"]
