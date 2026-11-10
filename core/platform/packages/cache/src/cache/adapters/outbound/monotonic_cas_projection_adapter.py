"""
Monotonic Watermark Compare-And-Set (CAS) Read Projection Cache Adapter.

Depends exclusively on `AtomicCacheStoreExecutorPort` (zero Adapter-to-Adapter
coupling). Guarantees mathematically monotonic cache updates so lagged Read
Replica backfills can never overwrite fresher Outbox Relay updates.
"""

from __future__ import annotations

import time
import urllib.parse
from collections.abc import Callable, Sequence

import structlog

from cache.domain.constants import (
    UPSERT_IF_NEWER_WATERMARK_LUA,
    CacheLookupStatus,
    CacheStoreOperationStatus,
    CacheUpsertStatus,
)
from cache.domain.models import (
    CacheLookupResult,
    CacheUpsertResult,
    StampedProjectionDTO,
)
from cache.ports.outbound.cache_store_executor_port import AtomicCacheStoreExecutorPort
from cache.ports.outbound.projection_cache_port import ReadProjectionCachePort

logger = structlog.get_logger(__name__)


def _default_epoch_ms() -> int:
    return int(time.time() * 1000)


def _encode_component(component: str) -> str:
    return urllib.parse.quote(component, safe="")


class MonotonicCasProjectionAdapter(ReadProjectionCachePort):
    """Production `ReadProjectionCachePort` backed by atomic Lua watermark CAS."""

    def __init__(
        self,
        store_executor: AtomicCacheStoreExecutorPort,
        key_prefix: str = "soopa:proj",
        clock_ms: Callable[[], int] = _default_epoch_ms,
    ) -> None:
        self._store = store_executor
        self._prefix = key_prefix
        self._clock_ms = clock_ms

    def _storage_key(self, namespace: str, tenant_id: str, projection_key: str) -> str:
        return (
            f"{self._prefix}:data:{_encode_component(namespace)}:"
            f"{_encode_component(tenant_id)}:{_encode_component(projection_key)}"
        )

    def _lease_key(self, namespace: str, tenant_id: str, projection_key: str) -> str:
        return (
            f"{self._prefix}:lease:{_encode_component(namespace)}:"
            f"{_encode_component(tenant_id)}:{_encode_component(projection_key)}"
        )

    async def get_projection(
        self,
        *,
        namespace: str,
        tenant_id: str,
        projection_key: str,
    ) -> CacheLookupResult:
        skey = self._storage_key(namespace, tenant_id, projection_key)
        stored = await self._store.read_projection_hash(skey)
        if stored.status == CacheStoreOperationStatus.UNAVAILABLE:
            logger.error(
                "projection_cache_lookup_store_error",
                namespace=namespace,
                tenant_id=tenant_id,
                projection_key=projection_key,
            )
            return CacheLookupResult(status=CacheLookupStatus.STORE_ERROR, projection=None)

        if (
            stored.payload_json is None
            or stored.source_watermark is None
            or stored.soft_expiry_epoch_ms is None
        ):
            return CacheLookupResult(status=CacheLookupStatus.MISS, projection=None)

        projection = StampedProjectionDTO(
            payload_json=stored.payload_json,
            source_watermark=stored.source_watermark,
        )
        now_ms = self._clock_ms()
        if now_ms >= stored.soft_expiry_epoch_ms:
            return CacheLookupResult(
                status=CacheLookupStatus.HIT_STALE_REVALIDATE,
                projection=projection,
            )
        return CacheLookupResult(
            status=CacheLookupStatus.HIT_FRESH,
            projection=projection,
        )

    async def upsert_projection_monotonic(
        self,
        *,
        namespace: str,
        tenant_id: str,
        projection_key: str,
        projection: StampedProjectionDTO,
        soft_ttl_seconds: int,
        hard_ttl_seconds: int,
    ) -> CacheUpsertResult:
        if soft_ttl_seconds <= 0 or hard_ttl_seconds < soft_ttl_seconds:
            raise ValueError("Require 0 < soft_ttl_seconds <= hard_ttl_seconds")

        skey = self._storage_key(namespace, tenant_id, projection_key)
        soft_exp_ms = self._clock_ms() + (soft_ttl_seconds * 1000)
        cas_res = await self._store.eval_cas_script(
            script=UPSERT_IF_NEWER_WATERMARK_LUA,
            storage_key=skey,
            watermark=projection.source_watermark,
            payload_json=projection.payload_json,
            soft_expiry_epoch_ms=soft_exp_ms,
            hard_ttl_seconds=hard_ttl_seconds,
        )
        if cas_res.status == CacheStoreOperationStatus.UNAVAILABLE:
            logger.error(
                "projection_cache_upsert_store_error",
                namespace=namespace,
                tenant_id=tenant_id,
                projection_key=projection_key,
                candidate_watermark=projection.source_watermark,
            )
            return CacheUpsertResult(
                status=CacheUpsertStatus.STORE_ERROR,
                applied_watermark=None,
            )
        if cas_res.applied:
            return CacheUpsertResult(
                status=CacheUpsertStatus.APPLIED,
                applied_watermark=projection.source_watermark,
            )
        logger.debug(
            "projection_cas_skipped_stale_watermark",
            namespace=namespace,
            tenant_id=tenant_id,
            projection_key=projection_key,
            candidate_watermark=projection.source_watermark,
        )
        return CacheUpsertResult(
            status=CacheUpsertStatus.SKIPPED_STALE_WATERMARK,
            applied_watermark=None,
        )

    async def invalidate_projections(
        self,
        *,
        namespace: str,
        tenant_id: str,
        projection_keys: Sequence[str],
    ) -> int:
        if not projection_keys:
            return 0
        skeys = [self._storage_key(namespace, tenant_id, pk) for pk in projection_keys]
        return await self._store.delete_storage_keys(skeys)

    async def try_claim_revalidation_lease(
        self,
        *,
        namespace: str,
        tenant_id: str,
        projection_key: str,
        lease_ttl_ms: int = 2000,
    ) -> bool:
        lkey = self._lease_key(namespace, tenant_id, projection_key)
        return await self._store.try_acquire_refresh_lease(lkey, lease_ttl_ms)


__all__ = ["MonotonicCasProjectionAdapter"]
