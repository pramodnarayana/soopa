from types import TracebackType
from typing import Self

import structlog
from config.settings import AppSettings
from pipeline.adapters.repository import SqlAlchemyRepositoryAdapter
from pipeline.ports.outbound.data_plane_outbox_repository_port import DataPlaneOutboxRepositoryPort
from pipeline.ports.outbound.edi_message_port import RepositoryPort
from pipeline.ports.outbound.storage_port import StoragePort
from sqlalchemy.ext.asyncio import AsyncSession

from worker.adapters.outbound.database.postgres_data_plane_outbox_repository import (
    SqlAlchemyDataPlaneOutboxRepository,
)

logger = structlog.get_logger(__name__)


class SqlAlchemyDataPlaneUnitOfWork:
    """
    Concrete Unit of Work for the EDI Worker Data Plane.

    Wires the pipeline's RepositoryPort (SqlAlchemyRepositoryAdapter) and the
    DataPlaneOutboxRepositoryPort (SqlAlchemyDataPlaneOutboxRepository) together
    behind a single async context manager to ensure atomic transaction boundaries.

    This satisfies the `pipeline.ports.outbound.data_plane_unit_of_work_port.DataPlaneUnitOfWorkPort` Protocol.
    """

    repository: RepositoryPort
    outbox: DataPlaneOutboxRepositoryPort

    def __init__(
        self,
        session: AsyncSession,
        settings: AppSettings,
        storage: StoragePort,
    ) -> None:
        self._session = session
        self._settings = settings
        self._storage = storage
        self.repository = SqlAlchemyRepositoryAdapter(
            session=session,
            settings=settings,
            storage=storage,
        )
        self.outbox = SqlAlchemyDataPlaneOutboxRepository(session=session)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        """Flushes and commits the current tenant session."""
        try:
            await self._session.flush()
            await self._session.commit()
        except Exception:
            await self.rollback()
            raise

    async def rollback(self) -> None:
        """Rolls back the current tenant session."""
        await self._session.rollback()
