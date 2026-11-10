"""
Centralized Platform Provider for Multi-Tenant & Cellular Sharding.

Assembles concrete `SqlAlchemyShardTopologyRepository` adapters with `TenantShardResolver`
so bounded contexts can provision shard resolvers without cross-package adapter coupling.
"""

from __future__ import annotations

from database.router import DatabaseRouterPort

from sharding.adapters.outbound.database.shard_topology_repository import (
    SqlAlchemyShardTopologyRepository,
)
from sharding.application.tenant_shard_resolver import TenantShardResolver
from sharding.ports.outbound.shard_topology_repository_port import (
    ShardTopologyRepositoryPort,
)


class SqlAlchemyTenantShardResolver(TenantShardResolver):
    """
    Pre-assembled SQLAlchemy-backed `TenantShardResolver` for bounded-context composition.
    """

    def __init__(
        self,
        db_router: DatabaseRouterPort,
        app_slug: str,
        ttl_secs: float = 300.0,
        max_entries: int = 1000,
    ) -> None:
        super().__init__(
            topology_repo=SqlAlchemyShardTopologyRepository(db_router=db_router),
            app_slug=app_slug,
            ttl_secs=ttl_secs,
            max_entries=max_entries,
        )
        self.db_router = db_router


class ShardingProvider:
    """Centralized Platform Provider for Sharding topology repositories and resolvers."""

    @classmethod
    def create_topology_repository(
        cls,
        db_router: DatabaseRouterPort,
    ) -> ShardTopologyRepositoryPort:
        """Create a SQLAlchemy-backed `ShardTopologyRepositoryPort`."""
        return SqlAlchemyShardTopologyRepository(db_router=db_router)

    @classmethod
    def create_tenant_shard_resolver(
        cls,
        db_router: DatabaseRouterPort,
        app_slug: str,
        ttl_secs: float = 300.0,
        max_entries: int = 1000,
    ) -> SqlAlchemyTenantShardResolver:
        """Create a SQLAlchemy-backed `TenantShardResolver` for `app_slug`."""
        return SqlAlchemyTenantShardResolver(
            db_router=db_router,
            app_slug=app_slug,
            ttl_secs=ttl_secs,
            max_entries=max_entries,
        )


__all__ = [
    "ShardingProvider",
    "SqlAlchemyTenantShardResolver",
]
