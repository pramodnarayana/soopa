"""Multi-Tenant Shard-Routed Data Plane Unit of Work Provider."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator, Callable
from typing import Generic, TypeVar

from seedwork.uow import UnitOfWorkPort

from sharding.ports.outbound.session_router_port import TenantWriteSessionRouterPort
from sharding.ports.outbound.shard_resolver_port import TenantShardResolverPort

TUoW = TypeVar("TUoW", bound=UnitOfWorkPort)
TSession = TypeVar("TSession")


class TenantDataPlaneUnitOfWorkProvider(Generic[TUoW, TSession]):
    """Generic multi-tenant Data Plane Unit of Work provider for any bounded context.

    Centralizes shard resolution, RLS-scoped TenantSession acquisition, and
    transactional UnitOfWork lifecycle management across multi-tenant apps (IP, EDI, etc.).
    """

    def __init__(
        self,
        resolver: TenantShardResolverPort,
        db_router: TenantWriteSessionRouterPort[TSession],
        uow_factory: Callable[[TSession], TUoW],
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


__all__ = ["TenantDataPlaneUnitOfWorkProvider"]
