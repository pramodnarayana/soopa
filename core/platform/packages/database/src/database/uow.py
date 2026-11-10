from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator, Callable
from types import TracebackType
from typing import Generic, Self, TypeVar

from seedwork.uow import UnitOfWorkPort
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database.interceptors import intercept_db_errors
from database.replication_watermark import parse_postgres_lsn
from database.router import DatabaseRouterPort
from database.tenant_shard_resolver import TenantShardResolverPort
from database.types import ReplicationWatermark, TenantSession

TUoW = TypeVar("TUoW", bound=UnitOfWorkPort)


class BaseSqlAlchemyUnitOfWork:
    """
    Centralized Base Unit of Work for all domains.

    Handles ACID transaction lifecycle, common error translation, and optional
    causal `ReplicationWatermark` capture for Read-Your-Own-Writes (RYOW).
    """

    session: AsyncSession
    last_commit_watermark: ReplicationWatermark | None

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._owns_transaction: bool = False
        self.last_commit_watermark = None

    async def __aenter__(self) -> Self:
        if not self.session.in_transaction():
            await self.session.begin()
            self._owns_transaction = True
        else:
            self._owns_transaction = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._owns_transaction and self.session.in_transaction():
            await self.rollback()

    async def capture_replication_watermark(self) -> ReplicationWatermark:
        """Sample current PostgreSQL `pg_current_wal_insert_lsn()` post-commit."""
        if self.session.in_transaction():
            raise RuntimeError(
                "Cannot capture replication watermark while a transaction is active; "
                "sampling must occur post-commit on the same writer to include the commit WAL record."
            )
        result = await self.session.execute(text("SELECT pg_current_wal_insert_lsn()::text"))
        lsn_text = str(result.scalar_one())
        watermark = parse_postgres_lsn(lsn_text)
        self.last_commit_watermark = watermark
        return watermark

    async def commit(self) -> None:
        try:
            await self._pre_commit()
            async with intercept_db_errors():
                await self.session.flush()
                await self.session.commit()
        except Exception:
            await self.rollback()
            raise

        await self._post_commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def _pre_commit(self) -> None:
        """Hook method called immediately before flushing and committing."""

    async def _post_commit(self) -> None:
        """Hook method called immediately after successful commit."""


class TenantDataPlaneUnitOfWorkProvider(Generic[TUoW]):
    """Generic multi-tenant Data Plane Unit of Work provider for any bounded context.

    Centralizes shard resolution, RLS-scoped TenantSession acquisition, and
    transactional UnitOfWork lifecycle management across multi-tenant apps (IP, EDI, etc.).
    """

    def __init__(
        self,
        resolver: TenantShardResolverPort,
        db_router: DatabaseRouterPort,
        uow_factory: Callable[[TenantSession], TUoW],
    ) -> None:
        self._resolver = resolver
        self._db_router = db_router
        self._uow_factory = uow_factory

    async def resolve_shard(self, tenant_id: str) -> tuple[str, str]:
        """Resolves `(shard_id, shard_dsn)` for the given `tenant_id`."""
        return await self._resolver.resolve_shard(tenant_id)

    @contextlib.asynccontextmanager
    async def get_data_plane_uow(
        self,
        tenant_id: str,
        shard_id: str,
        shard_dsn: str,
    ) -> AsyncGenerator[TUoW, None]:
        """Yields an RLS-isolated Data Plane Unit of Work bound to the resolved shard."""
        async with contextlib.aclosing(
            self._db_router.get_tenant_session(tenant_id, shard_id, shard_dsn)
        ) as session_gen:
            async for session in session_gen:
                uow = self._uow_factory(session)
                async with uow:
                    yield uow
                break


__all__ = [
    "BaseSqlAlchemyUnitOfWork",
    "TenantDataPlaneUnitOfWorkProvider",
]
