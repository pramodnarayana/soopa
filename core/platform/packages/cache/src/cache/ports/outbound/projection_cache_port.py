"""High-level Port for monotonic watermark-fenced Read Projection Caching."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from cache.domain.models import (
    CacheLookupResult,
    CacheUpsertResult,
    StampedProjectionDTO,
)


class ReadProjectionCachePort(Protocol):
    """
    Domain-agnostic Port consumed by Query Services and Outbox Projection Relays.
    """

    async def get_projection(
        self,
        *,
        namespace: str,
        tenant_id: str,
        projection_key: str,
    ) -> CacheLookupResult: ...

    async def upsert_projection_monotonic(
        self,
        *,
        namespace: str,
        tenant_id: str,
        projection_key: str,
        projection: StampedProjectionDTO,
        soft_ttl_seconds: int,
        hard_ttl_seconds: int,
    ) -> CacheUpsertResult: ...

    async def invalidate_projections(
        self,
        *,
        namespace: str,
        tenant_id: str,
        projection_keys: Sequence[str],
    ) -> int: ...

    async def try_claim_revalidation_lease(
        self,
        *,
        namespace: str,
        tenant_id: str,
        projection_key: str,
        lease_ttl_ms: int = 2000,
    ) -> bool: ...


__all__ = ["ReadProjectionCachePort"]
