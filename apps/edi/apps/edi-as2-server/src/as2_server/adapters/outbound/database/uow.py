import contextlib
from collections.abc import AsyncGenerator
from types import TracebackType

from database.router import DatabaseRouterPort
from edi.adapters.outbound.database.data_plane.outbox_repository import (
    SqlAlchemyDataPlaneOutboxRepository,
)
from sqlalchemy.ext.asyncio import AsyncSession

from as2_server.adapters.outbound.database.edi_message_repository import EdiMessageRepositoryAdapter
from as2_server.ports.outbound.uow_port import AS2UnitOfWorkPort


class SqlAlchemyAS2UnitOfWork(AS2UnitOfWorkPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.message_repo = EdiMessageRepositoryAdapter(self._session)
        self.outbox_repo = SqlAlchemyDataPlaneOutboxRepository(self._session)

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


class SqlAlchemyAS2UnitOfWorkFactory:
    def __init__(self, db_router: DatabaseRouterPort) -> None:
        self.db_router = db_router

    @contextlib.asynccontextmanager
    async def create_uow(
        self, tenant_id: str, shard_key: str, shard_url: str
    ) -> AsyncGenerator[SqlAlchemyAS2UnitOfWork, None]:
        async with contextlib.aclosing(
            self.db_router.get_tenant_session(tenant_id, shard_key, shard_url)
        ) as session_gen:
            async for session in session_gen:
                yield SqlAlchemyAS2UnitOfWork(session)
                break
