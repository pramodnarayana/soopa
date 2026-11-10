from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import cast

import pytest

from database.cellular_ring import ShardEndpointDTO, ShardResolutionOutcome
from database.consistency import (
    CausalWatermarkPolicy,
    InMemoryReplicaWatermarkStore,
    TokenBucketWriterFallbackBulkhead,
)
from database.constants import (
    DatabaseShardStatus,
    ShardResolutionStatus,
    ShardRoutingStrategy,
)
from database.query_provider import TenantDataPlaneQueryProvider
from database.router import DatabaseReadRouterPort
from database.tenant_shard_resolver import CellularShardResolverPort, TenantNotFoundError
from database.types import ReplicationWatermark, TenantReadSession
from database.utils import pgbouncer_transaction_connect_args


class _FakeCellularResolver(CellularShardResolverPort):
    def __init__(self, outcome: ShardResolutionOutcome) -> None:
        self._outcome = outcome

    async def resolve_tenant_endpoint(self, tenant_id: str) -> ShardResolutionOutcome:
        _ = tenant_id
        return self._outcome

    async def resolve_subject_endpoint(
        self, tenant_id: str, subject_key: str
    ) -> ShardResolutionOutcome:
        _ = (tenant_id, subject_key)
        return self._outcome


class _FakeReadRouter(DatabaseReadRouterPort):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def get_tenant_read_session(
        self, tenant_id: str, pool_key: str, target_dsn: str
    ) -> AsyncGenerator[TenantReadSession, None]:
        self.calls.append((tenant_id, pool_key, target_dsn))
        yield cast(TenantReadSession, object())


class _SampleQueryRepo:
    def __init__(self, session: TenantReadSession) -> None:
        self.session = session


def test_pgbouncer_transaction_connect_args_disables_statement_cache() -> None:
    args = pgbouncer_transaction_connect_args()
    assert args["statement_cache_size"] == 0
    assert args["server_settings"] == {"search_path": "public"}


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
    resolver = _FakeCellularResolver(
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
    resolver = _FakeCellularResolver(
        ShardResolutionOutcome(
            status=ShardResolutionStatus.NOT_FOUND,
            endpoint=None,
            reason="tenant_unmapped",
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
    resolver = _FakeCellularResolver(
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
