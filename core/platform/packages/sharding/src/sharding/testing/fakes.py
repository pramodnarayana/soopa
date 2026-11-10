"""Pure In-Memory Test Doubles for Multi-Tenant & Cellular Sharding."""

from __future__ import annotations

from collections.abc import Sequence

from sharding.domain.constants import ShardResolutionStatus
from sharding.domain.exceptions import TenantNotFoundError
from sharding.domain.topology import (
    ShardEndpointDTO,
    ShardResolutionOutcome,
    VirtualBucketAssignmentDTO,
)
from sharding.ports.outbound.shard_resolver_port import (
    CellularShardResolverPort,
    TenantShardResolverPort,
)
from sharding.ports.outbound.shard_topology_repository_port import (
    ShardTopologyRepositoryPort,
)


class InMemoryShardTopologyRepository(ShardTopologyRepositoryPort):
    """
    Strongly-typed in-memory implementation of `ShardTopologyRepositoryPort` for unit testing.
    """

    def __init__(
        self,
        *,
        tenants_by_app: dict[str, list[str]] | None = None,
        endpoints_by_tenant_app: dict[tuple[str, str], ShardEndpointDTO] | None = None,
        bucket_assignments_by_app: (
            dict[str, list[tuple[VirtualBucketAssignmentDTO, ShardEndpointDTO]]] | None
        ) = None,
    ) -> None:
        self._tenants_by_app: dict[str, list[str]] = (
            {k: list(v) for k, v in tenants_by_app.items()} if tenants_by_app else {}
        )
        self._endpoints_by_tenant_app: dict[tuple[str, str], ShardEndpointDTO] = (
            dict(endpoints_by_tenant_app) if endpoints_by_tenant_app else {}
        )
        self._bucket_assignments_by_app: dict[
            str, list[tuple[VirtualBucketAssignmentDTO, ShardEndpointDTO]]
        ] = (
            {k: list(v) for k, v in bucket_assignments_by_app.items()}
            if bucket_assignments_by_app
            else {}
        )
        self.tenant_lookup_calls: list[tuple[str, str]] = []
        self.list_tenants_calls: list[str] = []
        self.bucket_lookup_calls: list[str] = []

    def set_tenant_endpoint(
        self,
        tenant_id: str,
        app_slug: str,
        endpoint: ShardEndpointDTO,
    ) -> None:
        self._endpoints_by_tenant_app[(tenant_id, app_slug)] = endpoint
        tenants = self._tenants_by_app.setdefault(app_slug, [])
        if tenant_id not in tenants:
            tenants.append(tenant_id)

    def set_bucket_assignments(
        self,
        app_slug: str,
        pairs: Sequence[tuple[VirtualBucketAssignmentDTO, ShardEndpointDTO]],
    ) -> None:
        self._bucket_assignments_by_app[app_slug] = list(pairs)

    async def list_tenant_ids_for_app(self, app_slug: str) -> list[str]:
        self.list_tenants_calls.append(app_slug)
        return list(self._tenants_by_app.get(app_slug, []))

    async def get_tenant_shard_endpoint(
        self,
        tenant_id: str,
        app_slug: str,
    ) -> ShardEndpointDTO | None:
        self.tenant_lookup_calls.append((tenant_id, app_slug))
        return self._endpoints_by_tenant_app.get((tenant_id, app_slug))

    async def list_virtual_bucket_assignments_for_app(
        self,
        app_slug: str,
    ) -> list[tuple[VirtualBucketAssignmentDTO, ShardEndpointDTO]]:
        self.bucket_lookup_calls.append(app_slug)
        return list(self._bucket_assignments_by_app.get(app_slug, []))


class FakeCellularShardResolver(TenantShardResolverPort, CellularShardResolverPort):
    """Deterministic fake resolver for unit-testing `TenantDataPlaneQueryProvider` and UoW providers."""

    def __init__(self, outcome: ShardResolutionOutcome) -> None:
        self._outcome = outcome

    async def get_all_tenant_ids(self) -> list[str]:
        return []

    async def resolve_shard(self, tenant_id: str) -> tuple[str, str]:
        if (
            self._outcome.status == ShardResolutionStatus.NOT_FOUND
            or self._outcome.endpoint is None
        ):
            raise TenantNotFoundError(f"Tenant {tenant_id} not found in Global DB")
        return self._outcome.endpoint.shard_id, self._outcome.endpoint.writer_dsn

    async def resolve_tenant_endpoint(self, tenant_id: str) -> ShardResolutionOutcome:
        _ = tenant_id
        return self._outcome

    async def resolve_subject_endpoint(
        self,
        tenant_id: str,
        subject_key: str,
    ) -> ShardResolutionOutcome:
        _ = (tenant_id, subject_key)
        return self._outcome


__all__ = [
    "FakeCellularShardResolver",
    "InMemoryShardTopologyRepository",
]
