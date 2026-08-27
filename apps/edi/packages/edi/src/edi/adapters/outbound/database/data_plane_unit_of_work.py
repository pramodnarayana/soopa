import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from database.uow import BaseSqlAlchemyUnitOfWork
from edi.adapters.outbound.database.postgres_data_plane_outbox_repository import (
    SqlAlchemyDataPlaneOutboxRepository,
)
from edi.adapters.outbound.pipeline.repository import SqlAlchemyRepositoryAdapter
from edi.config.settings import AppSettings
from edi.ports.outbound.data_plane_outbox_repository_port import DataPlaneOutboxRepositoryPort
from edi.ports.outbound.edi_message_port import RepositoryPort
from edi.ports.outbound.storage_port import StoragePort

logger = structlog.get_logger(__name__)


class SqlAlchemyDataPlaneUnitOfWork(BaseSqlAlchemyUnitOfWork):
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
        super().__init__(session)
        self._settings = settings
        self._storage = storage
        self.repository = SqlAlchemyRepositoryAdapter(
            session=session,
            settings=settings,
            storage=storage,
        )
        self.outbox = SqlAlchemyDataPlaneOutboxRepository(session=session)
