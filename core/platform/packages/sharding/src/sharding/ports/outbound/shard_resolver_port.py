"""Abstract Ports for Multi-Tenant and Cellular Pod Resolution."""

from __future__ import annotations

from typing import Protocol

from sharding.domain.topology import ShardResolutionOutcome


class TenantShardResolverPort(Protocol):
    """Abstract Port for resolving `(shard_id, writer_dsn)` tenant assignments."""

    async def get_all_tenant_ids(self) -> list[str]:
        """Fetch all active tenant IDs subscribed to this application."""
        ...

    async def resolve_shard(self, tenant_id: str) -> tuple[str, str]:
        """Resolve a `tenant_id` to `(shard_id, writer_dsn)`."""
        ...


class CellularShardResolverPort(Protocol):
    """First-class CQRS & Cellular Pod resolution Port returning structured outcomes."""

    async def resolve_tenant_endpoint(self, tenant_id: str) -> ShardResolutionOutcome:
        """Resolve full Writer + Reader Pod endpoints for a tenant without exceptions."""
        ...

    async def resolve_subject_endpoint(
        self,
        tenant_id: str,
        subject_key: str,
    ) -> ShardResolutionOutcome:
        """Resolve Cellular Pod endpoint via 4,096-bucket consistent ring or tenant fallback."""
        ...


__all__ = [
    "CellularShardResolverPort",
    "TenantShardResolverPort",
]
