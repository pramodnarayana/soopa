from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession

from identity_worker.ports.outbound.identity_sync_repository_port import (
    IdentitySyncRepositoryPort,
    IdentitySyncUnitOfWorkPort,
)


class SqlAlchemyIdentitySyncUnitOfWork(IdentitySyncUnitOfWorkPort):
    def __init__(
        self,
        session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
        *,
        repo_factory: Callable[[AsyncSession], IdentitySyncRepositoryPort],
    ) -> None:
        self.session_factory = session_factory
        self._repo_factory = repo_factory
        self._cm: AbstractAsyncContextManager[AsyncSession] | None = None
        self.session: AsyncSession | None = None
        self._repo: IdentitySyncRepositoryPort | None = None

    @property
    def repo(self) -> IdentitySyncRepositoryPort:
        if self._repo is None:
            raise RuntimeError("SqlAlchemyIdentitySyncUnitOfWork must be entered before use")
        return self._repo

    async def __aenter__(self) -> IdentitySyncUnitOfWorkPort:
        self._cm = self.session_factory()
        self.session = await self._cm.__aenter__()
        self._repo = self._repo_factory(self.session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._cm is not None:
            await self._cm.__aexit__(exc_type, exc_val, exc_tb)

    async def commit(self) -> None:
        if self.session:
            await self.session.commit()

    async def rollback(self) -> None:
        if self.session:
            await self.session.rollback()
