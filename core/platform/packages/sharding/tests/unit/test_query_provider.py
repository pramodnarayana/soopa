from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest

from sharding.application.query_provider import TenantDataPlaneQueryProvider
from sharding.application.read_consistency_policies import (
    CausalWatermarkPolicy,
    InMemoryReplicaWatermarkStore,
    TokenBucketWriterFallbackBulkhead,
)
from sharding.domain.constants import (
    DatabaseShardStatus,
    ShardResolutionFailureReason,
    ShardResolutionStatus,
    ShardRoutingStrategy,
)
from sharding.domain.exceptions import TenantNotFoundError
from sharding.domain.topology import (
    ReplicationWatermark,
    ShardEndpointDTO,
    ShardResolutionOutcome,
)
from sharding.ports.outbound.session_router_port import TenantReadSessionRouterPort
from sharding.testing.fakes import FakeCellularShardResolver


class _FakeReadSession:
    pass


class _FakeReadRouter(TenantReadSessionRouterPort[_FakeReadSession]):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def get_tenant_read_session(
        self,
        tenant_id: str,
        pool_key: str,
        target_dsn: str,
    ) -> AsyncGenerator[_FakeReadSession, None]:
        self.calls.append((tenant_id, pool_key, target_dsn))
        yield _FakeReadSession()


class _SampleQueryRepo:
    def __init__(self, session: _FakeReadSession) -> None:
        self.session = session


@pytest.mark.asyncio
async def test_query_provider_routes_queries_according_to_consistency_policy() -> None:
    endpoint = ShardEndpointDTO(
        shard_id="ucp_shard_01",
        shard_name="shard_01",
        writer_dsn="dsn://shard_01/writer",
        reader_dsn="dsn://shard_01/reader",
        status=DatabaseShardStatus.ACTIVE,
        routing_strategy=ShardRoutingStrategy.TENANT_REGISTRY,
    )
    resolver = FakeCellularShardResolver(
        ShardResolutionOutcome(status=ShardResolutionStatus.RESOLVED, endpoint=endpoint)
    )
    read_router = _FakeReadRouter()
    watermarks = InMemoryReplicaWatermarkStore()
    watermarks.record_watermark("ucp_shard_01", ReplicationWatermark(100))
    bulkhead = TokenBucketWriterFallbackBulkhead(capacity=5, refill_per_second=1.0)

    provider = TenantDataPlaneQueryProvider(
        resolver=resolver,
        read_router=read_router,
        query_repo_factory=_SampleQueryRepo,
        watermark_probe=watermarks,
        fallback_bulkhead=bulkhead,
    )

    async with provider.get_query_repository("iam_ten_abc123") as repo:
        assert isinstance(repo, _SampleQueryRepo)
    assert read_router.calls[-1] == (
        "iam_ten_abc123",
        "ucp_shard_01:reader",
        "dsn://shard_01/reader",
    )

    async with provider.get_subject_query_repository(
        "iam_ten_abc123",
        "usr_999",
        consistency_policy=CausalWatermarkPolicy(required_watermark=ReplicationWatermark(250)),
    ) as repo_ryow:
        assert isinstance(repo_ryow, _SampleQueryRepo)
    assert read_router.calls[-1] == (
        "iam_ten_abc123",
        "ucp_shard_01:writer",
        "dsn://shard_01/writer",
    )


@pytest.mark.asyncio
async def test_query_provider_raises_when_pod_unresolvable() -> None:
    resolver = FakeCellularShardResolver(
        ShardResolutionOutcome(
            status=ShardResolutionStatus.NOT_FOUND,
            endpoint=None,
            reason=ShardResolutionFailureReason.TENANT_UNMAPPED,
        )
    )
    provider = TenantDataPlaneQueryProvider(
        resolver=resolver,
        read_router=_FakeReadRouter(),
        query_repo_factory=_SampleQueryRepo,
    )
    with pytest.raises(TenantNotFoundError, match="Unable to resolve read Pod"):
        async with provider.get_query_repository("iam_ten_missing"):
            pass


@pytest.mark.asyncio
async def test_query_provider_causal_read_without_probe_raises_value_error() -> None:
    endpoint = ShardEndpointDTO(
        shard_id="ucp_shard_01",
        shard_name="shard_01",
        writer_dsn="dsn://shard_01/writer",
        reader_dsn="dsn://shard_01/reader",
        status=DatabaseShardStatus.ACTIVE,
        routing_strategy=ShardRoutingStrategy.TENANT_REGISTRY,
    )
    resolver = FakeCellularShardResolver(
        ShardResolutionOutcome(status=ShardResolutionStatus.RESOLVED, endpoint=endpoint)
    )
    provider = TenantDataPlaneQueryProvider(
        resolver=resolver,
        read_router=_FakeReadRouter(),
        query_repo_factory=_SampleQueryRepo,
        watermark_probe=None,
    )
    with pytest.raises(ValueError, match="A live ReplicaWatermarkProbePort must be supplied"):
        async with provider.get_query_repository(
            "iam_ten_abc123",
            consistency_policy=CausalWatermarkPolicy(required_watermark=ReplicationWatermark(10)),
        ):
            pass

    with pytest.raises(ValueError, match="A live ReplicaWatermarkProbePort must be supplied"):
        TenantDataPlaneQueryProvider(
            resolver=resolver,
            read_router=_FakeReadRouter(),
            query_repo_factory=_SampleQueryRepo,
            watermark_probe=None,
            default_policy=CausalWatermarkPolicy(required_watermark=ReplicationWatermark(10)),
        )
