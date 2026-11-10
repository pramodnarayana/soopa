from __future__ import annotations

import time

import pytest

from sharding.application.tenant_shard_resolver import TenantShardResolver
from sharding.domain.constants import (
    DatabaseShardStatus,
    ShardResolutionFailureReason,
    ShardResolutionStatus,
    ShardRoutingStrategy,
)
from sharding.domain.exceptions import TenantNotFoundError
from sharding.domain.topology import ShardEndpointDTO, VirtualBucketAssignmentDTO
from sharding.testing.fakes import InMemoryShardTopologyRepository


def _endpoint(
    shard_id: str,
    writer_dsn: str,
    *,
    name: str = "shard_name",
    reader_dsn: str | None = None,
    status: DatabaseShardStatus = DatabaseShardStatus.ACTIVE,
    routing_strategy: ShardRoutingStrategy = ShardRoutingStrategy.TENANT_REGISTRY,
) -> ShardEndpointDTO:
    return ShardEndpointDTO(
        shard_id=shard_id,
        shard_name=name,
        writer_dsn=writer_dsn,
        reader_dsn=reader_dsn or writer_dsn,
        status=status,
        routing_strategy=routing_strategy,
    )


@pytest.mark.asyncio
async def test_tenant_shard_resolver_hit_and_cache() -> None:
    repo = InMemoryShardTopologyRepository()
    repo.set_tenant_endpoint("ten_1", "ip", _endpoint("shard_ip_1", "postgresql://dsn1"))
    resolver = TenantShardResolver(topology_repo=repo, app_slug="ip", ttl_secs=300)

    # 1. First resolution queries topology repository
    shard_id, shard_dsn = await resolver.resolve_shard("ten_1")
    assert shard_id == "shard_ip_1"
    assert shard_dsn == "postgresql://dsn1"
    assert len(repo.tenant_lookup_calls) == 1

    # 2. Second resolution hits in-memory cache without another repository call
    shard_id_cached, shard_dsn_cached = await resolver.resolve_shard("ten_1")
    assert shard_id_cached == "shard_ip_1"
    assert shard_dsn_cached == "postgresql://dsn1"
    assert len(repo.tenant_lookup_calls) == 1


@pytest.mark.asyncio
async def test_tenant_shard_resolver_not_found_raises() -> None:
    repo = InMemoryShardTopologyRepository()
    resolver = TenantShardResolver(topology_repo=repo, app_slug="ip", ttl_secs=300)

    with pytest.raises(TenantNotFoundError, match="Tenant ten_missing not found in Global DB"):
        await resolver.resolve_shard("ten_missing")

    with pytest.raises(ValueError):
        await resolver.resolve_shard("ten_missing")


@pytest.mark.asyncio
async def test_tenant_shard_resolver_cache_expiry() -> None:
    repo = InMemoryShardTopologyRepository()
    repo.set_tenant_endpoint("ten_1", "ip", _endpoint("shard_ip_1", "postgresql://dsn1"))
    resolver = TenantShardResolver(topology_repo=repo, app_slug="ip", ttl_secs=0.01)

    shard_id, shard_dsn = await resolver.resolve_shard("ten_1")
    assert shard_id == "shard_ip_1"
    assert shard_dsn == "postgresql://dsn1"

    repo.set_tenant_endpoint("ten_1", "ip", _endpoint("shard_ip_1", "postgresql://dsn1_updated"))
    time.sleep(0.02)

    shard_id2, shard_dsn2 = await resolver.resolve_shard("ten_1")
    assert shard_id2 == "shard_ip_1"
    assert shard_dsn2 == "postgresql://dsn1_updated"


@pytest.mark.asyncio
async def test_tenant_shard_resolver_lru_eviction() -> None:
    repo = InMemoryShardTopologyRepository()
    repo.set_tenant_endpoint("t1", "ip", _endpoint("s1", "dsn1"))
    repo.set_tenant_endpoint("t2", "ip", _endpoint("s2", "dsn2"))
    repo.set_tenant_endpoint("t3", "ip", _endpoint("s3", "dsn3"))
    resolver = TenantShardResolver(topology_repo=repo, app_slug="ip", ttl_secs=300, max_entries=2)

    await resolver.resolve_shard("t1")
    await resolver.resolve_shard("t2")
    assert len(resolver._endpoint_cache) == 2

    await resolver.resolve_shard("t3")
    assert len(resolver._endpoint_cache) == 2
    assert "t1" not in resolver._endpoint_cache
    assert "t2" in resolver._endpoint_cache
    assert "t3" in resolver._endpoint_cache


@pytest.mark.asyncio
async def test_tenant_shard_resolver_get_all_tenant_ids() -> None:
    repo = InMemoryShardTopologyRepository(tenants_by_app={"ip": ["ten_1", "ten_2", "ten_3"]})
    resolver = TenantShardResolver(topology_repo=repo, app_slug="ip", ttl_secs=300)

    tenant_ids = await resolver.get_all_tenant_ids()
    assert tenant_ids == ["ten_1", "ten_2", "ten_3"]


@pytest.mark.asyncio
async def test_cellular_resolver_resolves_endpoint_with_reader_dsn_and_write_fence() -> None:
    repo = InMemoryShardTopologyRepository()
    repo.set_tenant_endpoint(
        "iam_ten_01",
        "edi",
        _endpoint(
            "ucp_shard_01",
            "dsn://pod01/writer",
            name="pod01",
            reader_dsn="dsn://pod01/reader",
            status=DatabaseShardStatus.WRITE_FENCED,
        ),
    )
    resolver = TenantShardResolver(topology_repo=repo, app_slug="edi", ttl_secs=300)

    assert resolver.app_slug == "edi"
    outcome = await resolver.resolve_tenant_endpoint("iam_ten_01")
    assert outcome.status == ShardResolutionStatus.WRITE_FENCED
    assert outcome.endpoint is not None
    assert outcome.endpoint.writer_dsn == "dsn://pod01/writer"
    assert outcome.endpoint.reader_dsn == "dsn://pod01/reader"

    cached = await resolver.resolve_tenant_endpoint("iam_ten_01")
    assert cached.status == ShardResolutionStatus.WRITE_FENCED
    assert len(repo.tenant_lookup_calls) == 1


@pytest.mark.asyncio
async def test_cellular_resolver_uses_virtual_bucket_ring_for_subjects() -> None:
    cell_a = _endpoint(
        "ucp_shard_cell_a",
        "dsn://cell_a/writer",
        reader_dsn="dsn://cell_a/reader",
        routing_strategy=ShardRoutingStrategy.VIRTUAL_BUCKET_RING,
    )
    cell_b = _endpoint(
        "ucp_shard_cell_b",
        "dsn://cell_b/writer",
        reader_dsn="dsn://cell_b/reader",
        routing_strategy=ShardRoutingStrategy.VIRTUAL_BUCKET_RING,
    )
    b1 = VirtualBucketAssignmentDTO("ucp_bkt_1", "ucp_app_1", 0, 2047, "ucp_shard_cell_a")
    b2 = VirtualBucketAssignmentDTO("ucp_bkt_2", "ucp_app_1", 2048, 4095, "ucp_shard_cell_b")

    repo = InMemoryShardTopologyRepository()
    repo.set_bucket_assignments("consumer", [(b1, cell_a), (b2, cell_b)])
    resolver = TenantShardResolver(topology_repo=repo, app_slug="consumer", ttl_secs=300)

    out1 = await resolver.resolve_subject_endpoint("iam_ten_global", "usr_alpha_1")
    out2 = await resolver.resolve_subject_endpoint("iam_ten_global", "usr_beta_2")
    assert out1.status == ShardResolutionStatus.RESOLVED
    assert out2.status == ShardResolutionStatus.RESOLVED
    assert len(repo.bucket_lookup_calls) == 1


@pytest.mark.asyncio
async def test_cellular_resolver_caches_empty_ring_assignments() -> None:
    repo = InMemoryShardTopologyRepository()
    repo.set_tenant_endpoint(
        "iam_ten_01",
        "consumer",
        _endpoint(
            "ucp_shard_01",
            "dsn://pod01/writer",
            name="pod01",
            reader_dsn="dsn://pod01/reader",
        ),
    )
    resolver = TenantShardResolver(topology_repo=repo, app_slug="consumer", ttl_secs=300)

    out1 = await resolver.resolve_subject_endpoint("iam_ten_01", "usr_1")
    assert out1.status == ShardResolutionStatus.RESOLVED
    assert out1.endpoint is not None
    assert out1.endpoint.shard_id == "ucp_shard_01"

    out2 = await resolver.resolve_subject_endpoint("iam_ten_01", "usr_2")
    assert out2.status == ShardResolutionStatus.RESOLVED
    assert len(repo.bucket_lookup_calls) == 1
    assert len(repo.tenant_lookup_calls) == 1


@pytest.mark.asyncio
async def test_cellular_resolver_invalid_ring_topology_returns_not_found() -> None:
    cell_a = _endpoint("ucp_shard_cell_a", "dsn://cell_a/writer")
    b_incomplete = VirtualBucketAssignmentDTO("ucp_bkt_1", "ucp_app_1", 0, 1000, "ucp_shard_cell_a")
    repo = InMemoryShardTopologyRepository()
    repo.set_bucket_assignments("consumer", [(b_incomplete, cell_a)])
    resolver = TenantShardResolver(topology_repo=repo, app_slug="consumer", ttl_secs=300)

    out1 = await resolver.resolve_subject_endpoint("iam_ten_global", "usr_1")
    assert out1.status == ShardResolutionStatus.NOT_FOUND
    assert out1.reason == ShardResolutionFailureReason.RING_TOPOLOGY_INVALID

    out2 = await resolver.resolve_subject_endpoint("iam_ten_global", "usr_2")
    assert out2.status == ShardResolutionStatus.NOT_FOUND
    assert out2.reason == ShardResolutionFailureReason.RING_TOPOLOGY_INVALID
    assert len(repo.bucket_lookup_calls) == 1
