"""SQLAlchemy Unit of Work implementation for Integration Platform Control Plane."""

from __future__ import annotations

from ip.engine.adapters.outbound.database.control_plane.catalog_repository import (
    SqlAlchemyCatalogRepository,
)
from ip.engine.adapters.outbound.database.control_plane.connection_repository import (
    SqlAlchemyConnectionRepository,
)
from ip.engine.adapters.outbound.database.control_plane.stream_state_repository import (
    SqlAlchemyStreamStateRepository,
)
from ip.engine.ports.outbound.catalog_repository_port import CatalogRepositoryPort
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.engine.ports.outbound.stream_state_repository_port import StreamStateRepositoryPort
from ip.engine.ports.outbound.uow import ControlPlaneUnitOfWorkPort
from sqlalchemy.ext.asyncio import AsyncSession

from database.uow import BaseSqlAlchemyUnitOfWork


class SqlAlchemyControlPlaneUnitOfWork(BaseSqlAlchemyUnitOfWork, ControlPlaneUnitOfWorkPort):
    """Concrete Unit of Work for the Integration Platform Control Plane (global_db, schema 'ip')."""

    connections: ConnectionRepositoryPort
    catalogs: CatalogRepositoryPort
    stream_states: StreamStateRepositoryPort

    def __init__(self, global_session: AsyncSession) -> None:
        super().__init__(global_session)
        self.global_session = global_session
        self.connections = SqlAlchemyConnectionRepository(global_session)
        self.catalogs = SqlAlchemyCatalogRepository(global_session)
        self.stream_states = SqlAlchemyStreamStateRepository(global_session)


__all__ = ["SqlAlchemyControlPlaneUnitOfWork"]
