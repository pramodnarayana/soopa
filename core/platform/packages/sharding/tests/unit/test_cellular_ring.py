from __future__ import annotations

import pytest

from sharding.domain.cellular_ring import (
    VirtualBucketRing,
    compute_virtual_bucket,
)
from sharding.domain.constants import (
    VIRTUAL_BUCKET_RING_SIZE,
    DatabaseShardStatus,
    ShardResolutionStatus,
    ShardRoutingStrategy,
)
from sharding.domain.topology import (
    ShardEndpointDTO,
    VirtualBucketAssignmentDTO,
)


def _make_endpoint(
    shard_id: str,
    status: DatabaseShardStatus = DatabaseShardStatus.ACTIVE,
) -> ShardEndpointDTO:
    return ShardEndpointDTO(
        shard_id=shard_id,
        shard_name=f"name_{shard_id}",
        writer_dsn=f"dsn://{shard_id}/writer",
        reader_dsn=f"dsn://{shard_id}/reader",
        status=status,
        routing_strategy=ShardRoutingStrategy.VIRTUAL_BUCKET_RING,
    )


def test_compute_virtual_bucket_is_deterministic() -> None:
    b1 = compute_virtual_bucket("usr_8f9c02a1b2c3d4e5f6010203")
    b2 = compute_virtual_bucket("usr_8f9c02a1b2c3d4e5f6010203")
    assert b1 == b2
    assert 0 <= b1 < VIRTUAL_BUCKET_RING_SIZE

    with pytest.raises(ValueError, match="subject_key must be non-empty"):
        compute_virtual_bucket("   ")
    with pytest.raises(ValueError, match="ring_size must be strictly positive"):
        compute_virtual_bucket("usr_1", ring_size=0)


def test_virtual_bucket_ring_resolves_read_vs_write_fenced_pods() -> None:
    s1 = _make_endpoint("ucp_shard_cell_01")
    s2 = _make_endpoint("ucp_shard_cell_02", status=DatabaseShardStatus.WRITE_FENCED)

    assignments = [
        VirtualBucketAssignmentDTO(
            assignment_id="ucp_bkt_01",
            app_id="ucp_app_consumer",
            bucket_start=0,
            bucket_end=2047,
            shard_id=s1.shard_id,
        ),
        VirtualBucketAssignmentDTO(
            assignment_id="ucp_bkt_02",
            app_id="ucp_app_consumer",
            bucket_start=2048,
            bucket_end=4095,
            shard_id=s2.shard_id,
        ),
    ]
    ring = VirtualBucketRing.from_assignments(
        assignments=assignments,
        shards_by_id={s1.shard_id: s1, s2.shard_id: s2},
    )

    out_low = ring.resolve_bucket(0)
    assert out_low.status == ShardResolutionStatus.RESOLVED
    assert out_low.endpoint == s1
    assert out_low.virtual_bucket == 0

    out_fenced_for_write = ring.resolve_bucket_for_write(3000)
    assert out_fenced_for_write.status == ShardResolutionStatus.WRITE_FENCED
    assert out_fenced_for_write.endpoint == s2

    out_fenced_for_read = ring.resolve_bucket(3000)
    assert out_fenced_for_read.status == ShardResolutionStatus.RESOLVED
    assert out_fenced_for_read.endpoint == s2

    out_out_of_bounds = ring.resolve_bucket(9999)
    assert out_out_of_bounds.status == ShardResolutionStatus.NOT_FOUND

    subject_read = ring.resolve_subject("usr_0001")
    assert subject_read.status == ShardResolutionStatus.RESOLVED
    subject_write = ring.resolve_subject_for_write("usr_0001")
    assert subject_write.status in (
        ShardResolutionStatus.RESOLVED,
        ShardResolutionStatus.WRITE_FENCED,
    )


def test_virtual_bucket_ring_rejects_invalid_topologies() -> None:
    s1 = _make_endpoint("ucp_shard_cell_01")
    with pytest.raises(ValueError, match=r"VirtualBucketRing must cover 0\.\.4095"):
        VirtualBucketRing.from_assignments(assignments=[], shards_by_id={})

    incomplete = [
        VirtualBucketAssignmentDTO(
            assignment_id="ucp_bkt_01",
            app_id="ucp_app_consumer",
            bucket_start=0,
            bucket_end=2000,
            shard_id=s1.shard_id,
        )
    ]
    with pytest.raises(ValueError, match=r"VirtualBucketRing must cover 0\.\.4095"):
        VirtualBucketRing.from_assignments(
            assignments=incomplete,
            shards_by_id={s1.shard_id: s1},
        )
