from __future__ import annotations

import pytest

from database.cellular_ring import ShardEndpointDTO
from database.consistency import (
    CausalWatermarkPolicy,
    EventualReplicaPolicy,
    InMemoryReplicaWatermarkStore,
    StrictPrimaryPolicy,
    TokenBucketWriterFallbackBulkhead,
)
from database.constants import DatabaseShardStatus, ReadTargetRole, ShardRoutingStrategy
from database.types import ReplicationWatermark


def _sample_endpoint() -> ShardEndpointDTO:
    return ShardEndpointDTO(
        shard_id="ucp_shard_pod_01",
        shard_name="pod_01",
        writer_dsn="dsn://pod_01/writer",
        reader_dsn="dsn://pod_01/reader",
        status=DatabaseShardStatus.ACTIVE,
        routing_strategy=ShardRoutingStrategy.TENANT_REGISTRY,
    )


def test_eventual_policy_selects_reader_pool() -> None:
    endpoint = _sample_endpoint()
    watermarks = InMemoryReplicaWatermarkStore()
    bulkhead = TokenBucketWriterFallbackBulkhead(capacity=5, refill_per_second=1.0)

    ev_decision = EventualReplicaPolicy().select_route(endpoint, watermarks, bulkhead)
    assert ev_decision.target_role == ReadTargetRole.READER
    assert ev_decision.target_dsn == "dsn://pod_01/reader"
    assert ev_decision.pool_key == "ucp_shard_pod_01:reader"
    assert ev_decision.fallback_used is False


def test_strict_primary_policy_selects_writer_pool() -> None:
    endpoint = _sample_endpoint()
    watermarks = InMemoryReplicaWatermarkStore()
    bulkhead = TokenBucketWriterFallbackBulkhead(capacity=5, refill_per_second=1.0)

    pr_decision = StrictPrimaryPolicy().select_route(endpoint, watermarks, bulkhead)
    assert pr_decision.target_role == ReadTargetRole.WRITER
    assert pr_decision.target_dsn == "dsn://pod_01/writer"
    assert pr_decision.pool_key == "ucp_shard_pod_01:writer"
    assert pr_decision.fallback_used is False


def test_causal_watermark_policy_routes_to_reader_when_caught_up() -> None:
    endpoint = _sample_endpoint()
    watermarks = InMemoryReplicaWatermarkStore()
    watermarks.record_watermark(endpoint.shard_id, ReplicationWatermark(5000))
    bulkhead = TokenBucketWriterFallbackBulkhead(capacity=2, refill_per_second=1.0)

    decision = CausalWatermarkPolicy(required_watermark=ReplicationWatermark(4500)).select_route(
        endpoint, watermarks, bulkhead
    )
    assert decision.target_role == ReadTargetRole.READER
    assert decision.target_dsn == "dsn://pod_01/reader"
    assert decision.fallback_used is False
    assert decision.observed_watermark == ReplicationWatermark(5000)


def test_causal_watermark_policy_throttles_writer_fallback_via_bulkhead() -> None:
    clock = [100.0]
    endpoint = _sample_endpoint()
    watermarks = InMemoryReplicaWatermarkStore()
    watermarks.record_watermark(endpoint.shard_id, ReplicationWatermark(1000))
    bulkhead = TokenBucketWriterFallbackBulkhead(
        capacity=2,
        refill_per_second=1.0,
        clock=lambda: clock[0],
    )
    policy = CausalWatermarkPolicy(required_watermark=ReplicationWatermark(2000))

    d1 = policy.select_route(endpoint, watermarks, bulkhead)
    d2 = policy.select_route(endpoint, watermarks, bulkhead)
    assert d1.target_role == ReadTargetRole.WRITER
    assert d1.fallback_used is True
    assert d2.target_role == ReadTargetRole.WRITER
    assert d2.fallback_used is True

    d3 = policy.select_route(endpoint, watermarks, bulkhead)
    assert d3.target_role == ReadTargetRole.READER
    assert d3.fallback_used is False

    clock[0] = 101.5
    d4 = policy.select_route(endpoint, watermarks, bulkhead)
    assert d4.target_role == ReadTargetRole.WRITER
    assert d4.fallback_used is True


def test_watermark_store_enforces_monotonic_advancement() -> None:
    store = InMemoryReplicaWatermarkStore()
    store.record_watermark("shard_1", ReplicationWatermark(250))
    store.record_watermark("shard_1", ReplicationWatermark(200))
    assert store.get_cached_watermark("shard_1") == ReplicationWatermark(250)


def test_token_bucket_bulkhead_validates_configuration() -> None:
    with pytest.raises(ValueError, match="capacity must be strictly positive"):
        TokenBucketWriterFallbackBulkhead(capacity=0)
    with pytest.raises(ValueError, match="refill_per_second must be strictly positive"):
        TokenBucketWriterFallbackBulkhead(capacity=1, refill_per_second=0.0)
