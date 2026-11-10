"""
Enterprise Multi-Tenant & Cellular Shard Resolution Application Service.

Provides sub-millisecond L1 TTL-cached Pod resolution across both:
1. B2B Tenant Registry Pods (`ShardRoutingStrategy.TENANT_REGISTRY` for EDI, IP)
2. Consumer 4,096-Bucket Consistent-Hash Rings (`ShardRoutingStrategy.VIRTUAL_BUCKET_RING`)

Strictly decoupled from SQLAlchemy and ORM models via `ShardTopologyRepositoryPort`.
"""

from __future__ import annotations

import time

import structlog

from sharding.domain.cellular_ring import VirtualBucketRing
from sharding.domain.constants import (
    DatabaseShardStatus,
    ShardResolutionFailureReason,
    ShardResolutionStatus,
)
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

logger = structlog.get_logger(__name__)


class TenantShardResolver(TenantShardResolverPort, CellularShardResolverPort):
    """
    Enterprise-grade Tenant & Cellular Shard Resolver with bounded LRU + TTL caching.
    """

    def __init__(
        self,
        topology_repo: ShardTopologyRepositoryPort,
        app_slug: str,
        ttl_secs: float = 300.0,
        max_entries: int = 1000,
    ) -> None:
        self._topology_repo = topology_repo
        self._app_slug = app_slug
        self._ttl = float(ttl_secs)
        self._max_entries = max_entries
        self._endpoint_cache: dict[str, tuple[ShardEndpointDTO, float]] = {}
        self._ring_cache: (
            tuple[VirtualBucketRing | None, float, ShardResolutionFailureReason | None] | None
        ) = None

    @property
    def app_slug(self) -> str:
        return self._app_slug

    def _sweep(self, now: float) -> None:
        expired_ep = [k for k, v in self._endpoint_cache.items() if v[1] <= now]
        for k in expired_ep:
            del self._endpoint_cache[k]

        if len(self._endpoint_cache) > self._max_entries:
            sorted_ep = sorted(self._endpoint_cache.items(), key=lambda x: x[1][1])
            to_evict_ep = len(self._endpoint_cache) - self._max_entries
            for k, _ in sorted_ep[:to_evict_ep]:
                del self._endpoint_cache[k]

    async def get_all_tenant_ids(self) -> list[str]:
        """Query the topology repository for all tenants registered for this app."""
        tenant_ids = await self._topology_repo.list_tenant_ids_for_app(self._app_slug)
        logger.debug(
            "tenant_shard_resolver_fetched_all_tenants",
            app_slug=self._app_slug,
            count=len(tenant_ids),
        )
        return tenant_ids

    async def resolve_shard(self, tenant_id: str) -> tuple[str, str]:
        """Resolve `(shard_id, writer_dsn)` for `tenant_id` with L1 TTL caching."""
        now = time.monotonic()
        self._sweep(now)

        tid_str = str(tenant_id)
        cached = self._endpoint_cache.get(tid_str)
        if cached is not None and now < cached[1]:
            return cached[0].shard_id, cached[0].writer_dsn

        endpoint = await self._topology_repo.get_tenant_shard_endpoint(tid_str, self._app_slug)
        if endpoint is None:
            logger.error(
                "tenant_shard_not_found",
                tenant_id=tid_str,
                app_slug=self._app_slug,
            )
            raise TenantNotFoundError(f"Tenant {tid_str} not found in Global DB")

        self._endpoint_cache[tid_str] = (endpoint, now + self._ttl)
        self._sweep(now)

        logger.info(
            "tenant_shard_resolved",
            tenant_id=tid_str,
            app_slug=self._app_slug,
            shard_id=endpoint.shard_id,
        )
        return endpoint.shard_id, endpoint.writer_dsn

    async def resolve_tenant_endpoint(self, tenant_id: str) -> ShardResolutionOutcome:
        """First-class non-throwing resolution of full Writer + Reader Pod endpoints."""
        now = time.monotonic()
        self._sweep(now)
        tid_str = str(tenant_id)

        cached = self._endpoint_cache.get(tid_str)
        if cached is not None and now < cached[1]:
            ep = cached[0]
            if ep.status == DatabaseShardStatus.INACTIVE:
                return ShardResolutionOutcome(
                    status=ShardResolutionStatus.NOT_FOUND,
                    endpoint=None,
                    reason=ShardResolutionFailureReason.SHARD_INACTIVE,
                )
            status = (
                ShardResolutionStatus.WRITE_FENCED
                if ep.status == DatabaseShardStatus.WRITE_FENCED
                else ShardResolutionStatus.RESOLVED
            )
            return ShardResolutionOutcome(status=status, endpoint=ep)

        endpoint = await self._topology_repo.get_tenant_shard_endpoint(tid_str, self._app_slug)
        if endpoint is None:
            logger.error(
                "tenant_endpoint_not_found",
                tenant_id=tid_str,
                app_slug=self._app_slug,
            )
            return ShardResolutionOutcome(
                status=ShardResolutionStatus.NOT_FOUND,
                endpoint=None,
                reason=ShardResolutionFailureReason.TENANT_UNMAPPED,
            )

        if endpoint.status == DatabaseShardStatus.INACTIVE:
            logger.error(
                "tenant_endpoint_shard_inactive",
                tenant_id=tid_str,
                shard_id=endpoint.shard_id,
                app_slug=self._app_slug,
            )
            return ShardResolutionOutcome(
                status=ShardResolutionStatus.NOT_FOUND,
                endpoint=None,
                reason=ShardResolutionFailureReason.SHARD_INACTIVE,
            )

        self._endpoint_cache[tid_str] = (endpoint, now + self._ttl)
        self._sweep(now)
        out_status = (
            ShardResolutionStatus.WRITE_FENCED
            if endpoint.status == DatabaseShardStatus.WRITE_FENCED
            else ShardResolutionStatus.RESOLVED
        )
        logger.info(
            "tenant_endpoint_resolved",
            tenant_id=tid_str,
            app_slug=self._app_slug,
            shard_id=endpoint.shard_id,
            status=out_status.value,
        )
        return ShardResolutionOutcome(status=out_status, endpoint=endpoint)

    async def _get_or_load_ring(
        self,
        now: float,
    ) -> tuple[VirtualBucketRing | None, ShardResolutionFailureReason | None]:
        if self._ring_cache is not None and now < self._ring_cache[1]:
            return self._ring_cache[0], self._ring_cache[2]

        pairs = await self._topology_repo.list_virtual_bucket_assignments_for_app(self._app_slug)
        if not pairs:
            self._ring_cache = (None, now + self._ttl, None)
            return None, None

        assignments: list[VirtualBucketAssignmentDTO] = []
        shards_by_id: dict[str, ShardEndpointDTO] = {}
        for assignment_dto, endpoint_dto in pairs:
            assignments.append(assignment_dto)
            if assignment_dto.shard_id not in shards_by_id:
                shards_by_id[assignment_dto.shard_id] = endpoint_dto

        try:
            ring = VirtualBucketRing.from_assignments(
                assignments=assignments,
                shards_by_id=shards_by_id,
            )
        except ValueError as exc:
            logger.error(
                "virtual_bucket_ring_topology_invalid",
                app_slug=self._app_slug,
                error=str(exc),
            )
            self._ring_cache = (
                None,
                now + self._ttl,
                ShardResolutionFailureReason.RING_TOPOLOGY_INVALID,
            )
            return None, ShardResolutionFailureReason.RING_TOPOLOGY_INVALID

        self._ring_cache = (ring, now + self._ttl, None)
        logger.info(
            "virtual_bucket_ring_compiled",
            app_slug=self._app_slug,
            range_count=len(assignments),
            shard_count=len(shards_by_id),
        )
        return ring, None

    async def resolve_subject_endpoint(
        self,
        tenant_id: str,
        subject_key: str,
    ) -> ShardResolutionOutcome:
        """Resolve Consumer subject via 4,096-bucket ring if configured, else tenant registry."""
        now = time.monotonic()
        ring, err = await self._get_or_load_ring(now)
        if err is not None:
            return ShardResolutionOutcome(
                status=ShardResolutionStatus.NOT_FOUND,
                endpoint=None,
                reason=err,
            )
        if ring is not None:
            return ring.resolve_subject(subject_key)
        return await self.resolve_tenant_endpoint(tenant_id)


__all__ = ["TenantShardResolver"]
