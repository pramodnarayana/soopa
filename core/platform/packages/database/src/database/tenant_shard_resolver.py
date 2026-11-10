"""
Enterprise Multi-Tenant & Cellular Shard Resolution.

Provides sub-millisecond L1 TTL-cached Pod resolution across both:
1. B2B Tenant Registry Pods (`ShardRoutingStrategy.TENANT_REGISTRY` for EDI, IP)
2. Consumer 4,096-Bucket Consistent-Hash Rings (`ShardRoutingStrategy.VIRTUAL_BUCKET_RING`)
"""

from __future__ import annotations

import contextlib
import time
from typing import Protocol

import structlog
from sqlalchemy import select

from database.cellular_ring import (
    ShardEndpointDTO,
    ShardResolutionOutcome,
    VirtualBucketAssignmentDTO,
    VirtualBucketRing,
)
from database.constants import (
    DatabaseShardStatus,
    ShardResolutionStatus,
    ShardRoutingStrategy,
)
from database.models.identity import Tenant
from database.models.sharding import (
    DatabaseShard,
    ShardRegistry,
    VirtualBucketAssignment,
)
from database.models.subscriptions import App
from database.router import DatabaseRouterPort

logger = structlog.get_logger(__name__)


class DatabaseInfrastructureError(Exception):
    """Base exception for database infrastructure operations."""


class TenantNotFoundError(DatabaseInfrastructureError, ValueError):
    """Raised by legacy exception-based callers when a tenant is unmapped."""


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


def _to_shard_endpoint_dto(shard_obj: DatabaseShard) -> ShardEndpointDTO:
    """Explicit strict dot-notation Data Mapper from `DatabaseShard` ORM to `ShardEndpointDTO`."""
    writer_dsn = str(shard_obj.dsn)
    reader_dsn = str(shard_obj.reader_dsn) if shard_obj.reader_dsn else writer_dsn
    return ShardEndpointDTO(
        shard_id=str(shard_obj.id),
        shard_name=str(shard_obj.name),
        writer_dsn=writer_dsn,
        reader_dsn=reader_dsn,
        status=DatabaseShardStatus(str(shard_obj.status)),
        routing_strategy=ShardRoutingStrategy(str(shard_obj.routing_strategy)),
    )


def _to_bucket_assignment_dto(row: VirtualBucketAssignment) -> VirtualBucketAssignmentDTO:
    """Explicit strict dot-notation Data Mapper from `VirtualBucketAssignment` ORM to DTO."""
    return VirtualBucketAssignmentDTO(
        assignment_id=str(row.id),
        app_id=str(row.app_id),
        bucket_start=int(row.bucket_start),
        bucket_end=int(row.bucket_end),
        shard_id=str(row.shard_id),
    )


class TenantShardResolver(TenantShardResolverPort, CellularShardResolverPort):
    """
    Enterprise-grade Tenant & Cellular Shard Resolver with bounded LRU + TTL caching.
    """

    def __init__(
        self,
        db_router: DatabaseRouterPort,
        app_slug: str,
        ttl_secs: float = 300.0,
        max_entries: int = 1000,
    ) -> None:
        self._db_router = db_router
        self._app_slug = app_slug
        self._ttl = float(ttl_secs)
        self._max_entries = max_entries
        self._cache: dict[str, tuple[str, str, float]] = {}
        self._endpoint_cache: dict[str, tuple[ShardEndpointDTO, float]] = {}
        self._ring_cache: tuple[VirtualBucketRing, float] | None = None

    @property
    def app_slug(self) -> str:
        return self._app_slug

    def _sweep(self, now: float) -> None:
        expired = [k for k, v in self._cache.items() if v[2] <= now]
        for k in expired:
            del self._cache[k]

        if len(self._cache) > self._max_entries:
            sorted_entries = sorted(self._cache.items(), key=lambda x: x[1][2])
            to_evict = len(self._cache) - self._max_entries
            for k, _ in sorted_entries[:to_evict]:
                del self._cache[k]

        expired_ep = [k for k, v in self._endpoint_cache.items() if v[1] <= now]
        for k in expired_ep:
            del self._endpoint_cache[k]

        if len(self._endpoint_cache) > self._max_entries:
            sorted_ep = sorted(self._endpoint_cache.items(), key=lambda x: x[1][1])
            to_evict_ep = len(self._endpoint_cache) - self._max_entries
            for k, _ in sorted_ep[:to_evict_ep]:
                del self._endpoint_cache[k]

    async def get_all_tenant_ids(self) -> list[str]:
        """Query the Global DB for all tenants registered for this app."""
        async with contextlib.aclosing(self._db_router.get_global_session()) as session_gen:
            async for session in session_gen:
                stmt = (
                    select(Tenant.id)
                    .join(ShardRegistry, Tenant.id == ShardRegistry.tenant_id)
                    .join(App, App.id == ShardRegistry.app_id)
                    .where(App.slug == self._app_slug)
                )
                result = await session.execute(stmt)
                tenant_ids = [str(t_id) for t_id in result.scalars().all()]
                logger.debug(
                    "tenant_shard_resolver_fetched_all_tenants",
                    app_slug=self._app_slug,
                    count=len(tenant_ids),
                )
                return tenant_ids
        return []

    async def resolve_shard(self, tenant_id: str) -> tuple[str, str]:
        """Resolve `(shard_id, writer_dsn)` for `tenant_id` with L1 TTL caching."""
        now = time.monotonic()
        self._sweep(now)

        tid_str = str(tenant_id)
        if tid_str in self._cache:
            shard_name, shard_dsn, expiry = self._cache[tid_str]
            if now < expiry:
                return shard_name, shard_dsn

        async with contextlib.aclosing(self._db_router.get_global_session()) as session_gen:
            async for session in session_gen:
                stmt = (
                    select(Tenant, DatabaseShard)
                    .join(ShardRegistry, Tenant.id == ShardRegistry.tenant_id)
                    .join(DatabaseShard, ShardRegistry.shard_id == DatabaseShard.id)
                    .join(App, App.id == ShardRegistry.app_id)
                    .where(Tenant.id == tid_str, App.slug == self._app_slug)
                )
                result = await session.execute(stmt)
                row = result.first()
                if not row:
                    logger.error(
                        "tenant_shard_not_found",
                        tenant_id=tid_str,
                        app_slug=self._app_slug,
                    )
                    raise TenantNotFoundError(f"Tenant {tid_str} not found in Global DB")

                _, shard_obj = row
                shard_id = str(shard_obj.id)
                shard_dsn = str(shard_obj.dsn)

                self._cache[tid_str] = (shard_id, shard_dsn, now + self._ttl)
                self._sweep(now)

                logger.info(
                    "tenant_shard_resolved",
                    tenant_id=tid_str,
                    app_slug=self._app_slug,
                    shard_id=shard_id,
                )
                return shard_id, shard_dsn

        raise TenantNotFoundError(f"Tenant {tid_str} not found in Global DB")

    async def resolve_tenant_endpoint(self, tenant_id: str) -> ShardResolutionOutcome:
        """First-class non-throwing resolution of full Writer + Reader Pod endpoints."""
        now = time.monotonic()
        self._sweep(now)
        tid_str = str(tenant_id)

        cached = self._endpoint_cache.get(tid_str)
        if cached is not None and now < cached[1]:
            ep = cached[0]
            status = (
                ShardResolutionStatus.WRITE_FENCED
                if ep.status == DatabaseShardStatus.WRITE_FENCED
                else ShardResolutionStatus.RESOLVED
            )
            return ShardResolutionOutcome(status=status, endpoint=ep)

        async with contextlib.aclosing(self._db_router.get_global_session()) as session_gen:
            async for session in session_gen:
                stmt = (
                    select(DatabaseShard)
                    .join(ShardRegistry, DatabaseShard.id == ShardRegistry.shard_id)
                    .join(Tenant, Tenant.id == ShardRegistry.tenant_id)
                    .join(App, App.id == ShardRegistry.app_id)
                    .where(Tenant.id == tid_str, App.slug == self._app_slug)
                )
                result = await session.execute(stmt)
                shard_obj = result.scalars().first()
                if shard_obj is None:
                    logger.error(
                        "tenant_endpoint_not_found",
                        tenant_id=tid_str,
                        app_slug=self._app_slug,
                    )
                    return ShardResolutionOutcome(
                        status=ShardResolutionStatus.NOT_FOUND,
                        endpoint=None,
                        reason="tenant_unmapped",
                    )

                endpoint = _to_shard_endpoint_dto(shard_obj)
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
                        reason="shard_inactive",
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

        return ShardResolutionOutcome(
            status=ShardResolutionStatus.NOT_FOUND,
            endpoint=None,
            reason="global_session_unavailable",
        )

    async def _get_or_load_ring(self, now: float) -> VirtualBucketRing | None:
        if self._ring_cache is not None and now < self._ring_cache[1]:
            return self._ring_cache[0]

        async with contextlib.aclosing(self._db_router.get_global_session()) as session_gen:
            async for session in session_gen:
                stmt = (
                    select(VirtualBucketAssignment, DatabaseShard)
                    .join(App, App.id == VirtualBucketAssignment.app_id)
                    .join(DatabaseShard, DatabaseShard.id == VirtualBucketAssignment.shard_id)
                    .where(App.slug == self._app_slug)
                    .order_by(VirtualBucketAssignment.bucket_start.asc())
                )
                result = await session.execute(stmt)
                rows = list(result.all())
                if not rows:
                    return None

                assignments: list[VirtualBucketAssignmentDTO] = []
                shards_by_id: dict[str, ShardEndpointDTO] = {}
                for assignment_obj, shard_obj in rows:
                    dto = _to_bucket_assignment_dto(assignment_obj)
                    assignments.append(dto)
                    if dto.shard_id not in shards_by_id:
                        shards_by_id[dto.shard_id] = _to_shard_endpoint_dto(shard_obj)

                ring = VirtualBucketRing.from_assignments(
                    assignments=assignments,
                    shards_by_id=shards_by_id,
                )
                self._ring_cache = (ring, now + self._ttl)
                logger.info(
                    "virtual_bucket_ring_compiled",
                    app_slug=self._app_slug,
                    range_count=len(assignments),
                    shard_count=len(shards_by_id),
                )
                return ring
        return None

    async def resolve_subject_endpoint(
        self,
        tenant_id: str,
        subject_key: str,
    ) -> ShardResolutionOutcome:
        """Resolve Consumer subject via 4,096-bucket ring if configured, else tenant registry."""
        now = time.monotonic()
        ring = await self._get_or_load_ring(now)
        if ring is not None:
            return ring.resolve_subject(subject_key)
        return await self.resolve_tenant_endpoint(tenant_id)
