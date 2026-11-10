"""
Single-Flight Coalesced & Soft-TTL Read-Through Projection Service.

Eliminates hot-key cache stampedes (thundering herds) across Consumer and B2B
workloads by coalescing concurrent misses per `(namespace, tenant_id, key)` onto
a single upstream loader coroutine and refreshing soft-expired keys behind a
distributed millisecond lease.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import structlog

from cache.domain.constants import CacheLookupStatus
from cache.domain.models import StampedProjectionDTO
from cache.ports.outbound.projection_cache_port import ReadProjectionCachePort

logger = structlog.get_logger(__name__)

ProjectionLoader = Callable[[], Awaitable[StampedProjectionDTO | None]]


class ProjectionReadThroughService:
    """Orchestrates LSN/watermark-fenced read-through caching with stampede protection."""

    def __init__(self, cache: ReadProjectionCachePort) -> None:
        self._cache = cache
        self._inflight: dict[str, asyncio.Task[StampedProjectionDTO | None]] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()

    @staticmethod
    def _build_flight_key(namespace: str, tenant_id: str, projection_key: str) -> str:
        return f"{namespace}:{tenant_id}:{projection_key}"

    async def get_or_load_projection(
        self,
        *,
        namespace: str,
        tenant_id: str,
        projection_key: str,
        loader: ProjectionLoader,
        soft_ttl_seconds: int = 60,
        hard_ttl_seconds: int = 300,
        lease_ttl_ms: int = 2000,
    ) -> StampedProjectionDTO | None:
        """
        Return projection from hot cache or coalesce concurrent misses onto `loader`.
        """
        lookup = await self._cache.get_projection(
            namespace=namespace,
            tenant_id=tenant_id,
            projection_key=projection_key,
        )
        if lookup.status == CacheLookupStatus.HIT_FRESH and lookup.projection is not None:
            return lookup.projection

        if (
            lookup.status == CacheLookupStatus.HIT_STALE_REVALIDATE
            and lookup.projection is not None
        ):
            won_lease = await self._cache.try_claim_revalidation_lease(
                namespace=namespace,
                tenant_id=tenant_id,
                projection_key=projection_key,
                lease_ttl_ms=lease_ttl_ms,
            )
            if won_lease:
                logger.info(
                    "projection_soft_ttl_revalidation_scheduled",
                    namespace=namespace,
                    tenant_id=tenant_id,
                    projection_key=projection_key,
                )
                task = asyncio.create_task(
                    self._refresh_in_background(
                        namespace=namespace,
                        tenant_id=tenant_id,
                        projection_key=projection_key,
                        loader=loader,
                        soft_ttl_seconds=soft_ttl_seconds,
                        hard_ttl_seconds=hard_ttl_seconds,
                    )
                )
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
            else:
                logger.debug(
                    "projection_soft_ttl_revalidation_lease_skipped",
                    namespace=namespace,
                    tenant_id=tenant_id,
                    projection_key=projection_key,
                )
            return lookup.projection

        return await self._load_single_flight(
            namespace=namespace,
            tenant_id=tenant_id,
            projection_key=projection_key,
            loader=loader,
            soft_ttl_seconds=soft_ttl_seconds,
            hard_ttl_seconds=hard_ttl_seconds,
        )

    async def _load_single_flight(
        self,
        *,
        namespace: str,
        tenant_id: str,
        projection_key: str,
        loader: ProjectionLoader,
        soft_ttl_seconds: int,
        hard_ttl_seconds: int,
    ) -> StampedProjectionDTO | None:
        flight_key = self._build_flight_key(namespace, tenant_id, projection_key)
        existing = self._inflight.get(flight_key)
        if existing is not None:
            logger.debug(
                "projection_single_flight_coalesced",
                namespace=namespace,
                tenant_id=tenant_id,
                projection_key=projection_key,
            )
            return await asyncio.shield(existing)

        async def _do_load() -> StampedProjectionDTO | None:
            try:
                loaded = await loader()
                if loaded is not None:
                    await self._cache.upsert_projection_monotonic(
                        namespace=namespace,
                        tenant_id=tenant_id,
                        projection_key=projection_key,
                        projection=loaded,
                        soft_ttl_seconds=soft_ttl_seconds,
                        hard_ttl_seconds=hard_ttl_seconds,
                    )
                return loaded
            finally:
                self._inflight.pop(flight_key, None)

        task = asyncio.create_task(_do_load())
        self._inflight[flight_key] = task

        def _on_done(t: asyncio.Task[StampedProjectionDTO | None]) -> None:
            if not t.cancelled():
                _ = t.exception()

        task.add_done_callback(_on_done)
        return await asyncio.shield(task)

    async def _refresh_in_background(
        self,
        *,
        namespace: str,
        tenant_id: str,
        projection_key: str,
        loader: ProjectionLoader,
        soft_ttl_seconds: int,
        hard_ttl_seconds: int,
    ) -> None:
        try:
            loaded = await loader()
            if loaded is not None:
                await self._cache.upsert_projection_monotonic(
                    namespace=namespace,
                    tenant_id=tenant_id,
                    projection_key=projection_key,
                    projection=loaded,
                    soft_ttl_seconds=soft_ttl_seconds,
                    hard_ttl_seconds=hard_ttl_seconds,
                )
        except Exception:
            logger.exception(
                "projection_background_revalidation_failed",
                namespace=namespace,
                tenant_id=tenant_id,
                projection_key=projection_key,
            )

    async def drain_background_refreshes(self) -> None:
        """Await any pending soft-TTL revalidation tasks (useful on graceful shutdown)."""
        if self._background_tasks:
            await asyncio.gather(*tuple(self._background_tasks), return_exceptions=True)


__all__ = ["ProjectionLoader", "ProjectionReadThroughService"]
