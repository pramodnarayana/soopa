"""Outbound Port for querying Global Control Plane shard and cellular bucket topology."""

from __future__ import annotations

from typing import Protocol

from sharding.domain.topology import ShardEndpointDTO, VirtualBucketAssignmentDTO


class ShardTopologyRepositoryPort(Protocol):
    """DTO-first outbound Port encapsulating Global Control Plane shard topology lookups."""

    async def list_tenant_ids_for_app(self, app_slug: str) -> list[str]:
        """Fetch all active tenant IDs registered for `app_slug`."""
        ...

    async def get_tenant_shard_endpoint(
        self,
        tenant_id: str,
        app_slug: str,
    ) -> ShardEndpointDTO | None:
        """Fetch the mapped `ShardEndpointDTO` for `(tenant_id, app_slug)` or `None` if unmapped."""
        ...

    async def list_virtual_bucket_assignments_for_app(
        self,
        app_slug: str,
    ) -> list[tuple[VirtualBucketAssignmentDTO, ShardEndpointDTO]]:
        """Fetch ordered `(VirtualBucketAssignmentDTO, ShardEndpointDTO)` pairs for `app_slug`."""
        ...


__all__ = ["ShardTopologyRepositoryPort"]
