from __future__ import annotations

import pytest

from cache.adapters.outbound.monotonic_cas_projection_adapter import (
    MonotonicCasProjectionAdapter,
)
from cache.domain.constants import CacheLookupStatus, CacheUpsertStatus
from cache.domain.projection import StampedProjectionDTO
from cache.testing.fakes import InMemoryAtomicCacheStoreExecutor


@pytest.mark.asyncio
async def test_monotonic_cas_prevents_stale_replica_from_overwriting_newer_outbox_write() -> None:
    clock_ms = [1_000_000]
    store = InMemoryAtomicCacheStoreExecutor(clock_ms=lambda: clock_ms[0])
    adapter = MonotonicCasProjectionAdapter(
        store_executor=store,
        clock_ms=lambda: clock_ms[0],
    )

    # 1. Outbox Relay commits newer V2 (watermark=105) first
    v2 = StampedProjectionDTO(payload_json='{"status":"SHIPPED"}', source_watermark=105)
    out_v2 = await adapter.upsert_projection_monotonic(
        namespace="orders",
        tenant_id="iam_ten_01",
        projection_key="ord_9001",
        projection=v2,
        soft_ttl_seconds=60,
        hard_ttl_seconds=300,
    )
    assert out_v2.status == CacheUpsertStatus.APPLIED
    assert out_v2.applied_watermark == 105

    # 2. Lagged Read Replica finishes slow query with V1 (watermark=100) and attempts backfill
    v1_stale = StampedProjectionDTO(payload_json='{"status":"PENDING"}', source_watermark=100)
    out_v1 = await adapter.upsert_projection_monotonic(
        namespace="orders",
        tenant_id="iam_ten_01",
        projection_key="ord_9001",
        projection=v1_stale,
        soft_ttl_seconds=60,
        hard_ttl_seconds=300,
    )
    assert out_v1.status == CacheUpsertStatus.SKIPPED_STALE_WATERMARK
    assert out_v1.applied_watermark is None

    # 3. Verify V2 was NEVER overwritten!
    lookup = await adapter.get_projection(
        namespace="orders",
        tenant_id="iam_ten_01",
        projection_key="ord_9001",
    )
    assert lookup.status == CacheLookupStatus.HIT_FRESH
    assert lookup.projection == v2


@pytest.mark.asyncio
async def test_soft_ttl_and_hard_ttl_transitions_and_invalidation() -> None:
    clock_ms = [1_000_000]
    store = InMemoryAtomicCacheStoreExecutor(clock_ms=lambda: clock_ms[0])
    adapter = MonotonicCasProjectionAdapter(
        store_executor=store,
        clock_ms=lambda: clock_ms[0],
    )

    proj = StampedProjectionDTO(payload_json='{"feed":"v1"}', source_watermark=50)
    await adapter.upsert_projection_monotonic(
        namespace="feed",
        tenant_id="iam_ten_consumer",
        projection_key="home",
        projection=proj,
        soft_ttl_seconds=10,
        hard_ttl_seconds=30,
    )

    # Advance past soft TTL (10s = 10,000ms) -> HIT_STALE_REVALIDATE
    clock_ms[0] = 1_015_000
    stale_hit = await adapter.get_projection(
        namespace="feed",
        tenant_id="iam_ten_consumer",
        projection_key="home",
    )
    assert stale_hit.status == CacheLookupStatus.HIT_STALE_REVALIDATE
    assert stale_hit.projection == proj

    # Lease acquisition succeeds once within lease TTL window
    assert await adapter.try_claim_revalidation_lease(
        namespace="feed",
        tenant_id="iam_ten_consumer",
        projection_key="home",
        lease_ttl_ms=2000,
    )
    assert not await adapter.try_claim_revalidation_lease(
        namespace="feed",
        tenant_id="iam_ten_consumer",
        projection_key="home",
        lease_ttl_ms=2000,
    )

    # Advance past hard TTL (30s = 30,000ms) -> MISS
    clock_ms[0] = 1_035_000
    miss = await adapter.get_projection(
        namespace="feed",
        tenant_id="iam_ten_consumer",
        projection_key="home",
    )
    assert miss.status == CacheLookupStatus.MISS
    assert miss.projection is None

    # Re-populate and test explicit invalidation
    await adapter.upsert_projection_monotonic(
        namespace="feed",
        tenant_id="iam_ten_consumer",
        projection_key="home",
        projection=StampedProjectionDTO(payload_json='{"feed":"v2"}', source_watermark=60),
        soft_ttl_seconds=10,
        hard_ttl_seconds=30,
    )
    deleted = await adapter.invalidate_projections(
        namespace="feed",
        tenant_id="iam_ten_consumer",
        projection_keys=["home"],
    )
    assert deleted == 1
    assert (
        await adapter.invalidate_projections(
            namespace="feed",
            tenant_id="iam_ten_consumer",
            projection_keys=[],
        )
        == 0
    )

    with pytest.raises(ValueError, match="Require 0 < soft_ttl_seconds <= hard_ttl_seconds"):
        await adapter.upsert_projection_monotonic(
            namespace="feed",
            tenant_id="iam_ten_consumer",
            projection_key="home",
            projection=proj,
            soft_ttl_seconds=60,
            hard_ttl_seconds=10,
        )

    store.simulate_unavailable = True
    err_lookup = await adapter.get_projection(
        namespace="feed",
        tenant_id="iam_ten_consumer",
        projection_key="home",
    )
    assert err_lookup.status == CacheLookupStatus.STORE_ERROR
    err_upsert = await adapter.upsert_projection_monotonic(
        namespace="feed",
        tenant_id="iam_ten_consumer",
        projection_key="home",
        projection=proj,
        soft_ttl_seconds=10,
        hard_ttl_seconds=20,
    )
    assert err_upsert.status == CacheUpsertStatus.STORE_ERROR
