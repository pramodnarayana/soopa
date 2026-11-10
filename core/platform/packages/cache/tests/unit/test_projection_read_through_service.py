from __future__ import annotations

import asyncio

import pytest

from cache.adapters.outbound.monotonic_cas_projection_adapter import (
    MonotonicCasProjectionAdapter,
)
from cache.application.projection_read_through_service import ProjectionReadThroughService
from cache.domain.projection import StampedProjectionDTO
from cache.testing.fakes import InMemoryAtomicCacheStoreExecutor


@pytest.mark.asyncio
async def test_single_flight_coalesces_concurrent_cache_misses_into_one_replica_query() -> None:
    clock_ms = [5_000_000]
    store = InMemoryAtomicCacheStoreExecutor(clock_ms=lambda: clock_ms[0])
    cache_adapter = MonotonicCasProjectionAdapter(
        store_executor=store,
        clock_ms=lambda: clock_ms[0],
    )
    service = ProjectionReadThroughService(cache=cache_adapter)

    loader_invocations = 0

    async def _slow_replica_loader() -> StampedProjectionDTO | None:
        nonlocal loader_invocations
        loader_invocations += 1
        await asyncio.sleep(0.02)
        return StampedProjectionDTO(
            payload_json='{"catalog_id":"cat_hot"}',
            source_watermark=777,
        )

    # Fire 25 concurrent requests for the exact same uncached hot consumer key
    results = await asyncio.gather(
        *[
            service.get_or_load_projection(
                namespace="catalog",
                tenant_id="iam_ten_b2c",
                projection_key="cat_hot",
                loader=_slow_replica_loader,
                soft_ttl_seconds=60,
                hard_ttl_seconds=300,
            )
            for _ in range(25)
        ]
    )

    assert loader_invocations == 1
    assert all(r is not None and r.source_watermark == 777 for r in results)


@pytest.mark.asyncio
async def test_soft_ttl_serves_stale_immediately_and_refreshes_with_single_lease() -> None:
    clock_ms = [5_000_000]
    store = InMemoryAtomicCacheStoreExecutor(clock_ms=lambda: clock_ms[0])
    cache_adapter = MonotonicCasProjectionAdapter(
        store_executor=store,
        clock_ms=lambda: clock_ms[0],
    )
    service = ProjectionReadThroughService(cache=cache_adapter)

    await cache_adapter.upsert_projection_monotonic(
        namespace="catalog",
        tenant_id="iam_ten_b2c",
        projection_key="item_1",
        projection=StampedProjectionDTO(payload_json='{"price":100}', source_watermark=10),
        soft_ttl_seconds=5,
        hard_ttl_seconds=60,
    )

    # Move into soft-expired window (6s elapsed)
    clock_ms[0] = 5_006_000
    refresh_calls = 0

    async def _refresh_loader() -> StampedProjectionDTO | None:
        nonlocal refresh_calls
        refresh_calls += 1
        return StampedProjectionDTO(payload_json='{"price":120}', source_watermark=20)

    served = await service.get_or_load_projection(
        namespace="catalog",
        tenant_id="iam_ten_b2c",
        projection_key="item_1",
        loader=_refresh_loader,
        soft_ttl_seconds=5,
        hard_ttl_seconds=60,
    )
    assert served is not None
    assert served.source_watermark == 10

    await service.drain_background_refreshes()
    assert refresh_calls == 1

    refreshed = await service.get_or_load_projection(
        namespace="catalog",
        tenant_id="iam_ten_b2c",
        projection_key="item_1",
        loader=_refresh_loader,
        soft_ttl_seconds=5,
        hard_ttl_seconds=60,
    )
    assert refreshed is not None
    assert refreshed.source_watermark == 20


@pytest.mark.asyncio
async def test_single_flight_leader_cancellation_preserves_follower_completion() -> None:
    store = InMemoryAtomicCacheStoreExecutor()
    cache_adapter = MonotonicCasProjectionAdapter(store_executor=store)
    service = ProjectionReadThroughService(cache=cache_adapter)

    loader_started = asyncio.Event()

    async def _slow_loader() -> StampedProjectionDTO | None:
        loader_started.set()
        await asyncio.sleep(0.05)
        return StampedProjectionDTO(
            payload_json='{"status":"LOADED"}',
            source_watermark=999,
        )

    t1 = asyncio.create_task(
        service.get_or_load_projection(
            namespace="items",
            tenant_id="ten_01",
            projection_key="key_1",
            loader=_slow_loader,
        )
    )
    await loader_started.wait()

    t2 = asyncio.create_task(
        service.get_or_load_projection(
            namespace="items",
            tenant_id="ten_01",
            projection_key="key_1",
            loader=_slow_loader,
        )
    )

    t1.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t1

    result2 = await t2
    assert result2 is not None
    assert result2.source_watermark == 999
    assert result2.payload_json == '{"status":"LOADED"}'
