import contextlib
from collections.abc import AsyncGenerator, Callable
from types import TracebackType

from database.router import DatabaseRouterPort
from edi.ports.outbound.data_plane_outbox_repository_port import DataPlaneOutboxRepositoryPort
from sqlalchemy.ext.asyncio import AsyncSession

from as2_server.ports.outbound.repository_port import EdiMessageRepositoryPort
from as2_server.ports.outbound.uow_port import AS2UnitOfWorkFactoryPort, AS2UnitOfWorkPort


class SqlAlchemyAS2UnitOfWork(AS2UnitOfWorkPort):
    """SQLAlchemy Unit of Work for AS2 Server data-plane persistence."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        message_repo: EdiMessageRepositoryPort,
        outbox_repo: DataPlaneOutboxRepositoryPort,
    ) -> None:
        self._session = session
        self.message_repo = message_repo
        self.outbox_repo = outbox_repo

    async def __aenter__(self) -> "SqlAlchemyAS2UnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()
        else:
            await self.commit()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


class SqlAlchemyAS2UnitOfWorkFactory(AS2UnitOfWorkFactoryPort):
    """Resolves a tenant shard session and constructs an AS2UnitOfWorkPort via injected builder."""

    def __init__(
        self,
        db_router: DatabaseRouterPort,
        uow_builder: Callable[[AsyncSession], AS2UnitOfWorkPort],
    ) -> None:
        self.db_router = db_router
        self._uow_builder = uow_builder

    @contextlib.asynccontextmanager
    async def create_uow(
        self, tenant_id: str, shard_key: str, shard_url: str
    ) -> AsyncGenerator[AS2UnitOfWorkPort, None]:
        async with contextlib.aclosing(
            self.db_router.get_tenant_session(tenant_id, shard_key, shard_url)
        ) as session_gen:
            async for session in session_gen:
                yield self._uow_builder(session)
                break
