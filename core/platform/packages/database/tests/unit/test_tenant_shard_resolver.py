from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from typing import Any, cast

import pytest

from database.constants import ShardResolutionStatus
from database.router import DatabaseRouterPort
from database.tenant_shard_resolver import TenantNotFoundError, TenantShardResolver
from database.types import GlobalSession, TenantSession


class FakeSession:
    def __init__(self, execute_results: list[Any]) -> None:
        self.execute_results = list(execute_results)
        self.calls: list[Any] = []

    async def execute(self, stmt: Any) -> FakeResult:
        self.calls.append(stmt)
        if self.execute_results:
            return FakeResult(self.execute_results.pop(0))
        return FakeResult([])


class FakeResult:
    def __init__(self, data: Any) -> None:
        self._data = data

    def first(self) -> Any:
        if isinstance(self._data, list) and self._data:
            return self._data[0]
        return None

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._data if isinstance(self._data, list) else [])

    def all(self) -> list[Any]:
        return self._data if isinstance(self._data, list) else []


class FakeScalars:
    def __init__(self, data: list[Any]) -> None:
        self._data = data

    def all(self) -> list[Any]:
        return self._data

    def first(self) -> Any:
        return self._data[0] if self._data else None


class FakeDatabaseRouter(DatabaseRouterPort):
    def __init__(self, sessions: list[FakeSession]) -> None:
        self._sessions = list(sessions)

    async def get_global_session(self) -> AsyncGenerator[GlobalSession, None]:
        if self._sessions:
            session = self._sessions.pop(0)
            yield cast(GlobalSession, session)

    async def get_tenant_session(
        self, tenant_id: str, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]:
        if False:
            yield cast(TenantSession, None)

    async def get_shard_session(
        self, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]:
        if False:
            yield cast(TenantSession, None)

    async def get_all_shards(self, app_slug: str | None = None) -> list[tuple[str, str]]:
        return []

    async def close_all(self) -> None:
        pass


class FakeShardObj:
    def __init__(
        self,
        shard_id: str,
        shard_dsn: str,
        *,
        name: str = "shard_name",
        reader_dsn: str | None = None,
        status: str = "active",
        routing_strategy: str = "tenant_registry",
    ) -> None:
        self.id = shard_id
        self.dsn = shard_dsn
        self.name = name
        self.reader_dsn = reader_dsn
        self.status = status
        self.routing_strategy = routing_strategy


class FakeBucketAssignmentObj:
    def __init__(
        self,
        assignment_id: str,
        app_id: str,
        bucket_start: int,
        bucket_end: int,
        shard_id: str,
    ) -> None:
        self.id = assignment_id
        self.app_id = app_id
        self.bucket_start = bucket_start
        self.bucket_end = bucket_end
        self.shard_id = shard_id


class FakeTenantObj:
    def __init__(self, tenant_id: str) -> None:
        self.id = tenant_id


@pytest.mark.asyncio
async def test_tenant_shard_resolver_hit_and_cache() -> None:
    session = FakeSession(
        execute_results=[
            [(FakeTenantObj("ten_1"), FakeShardObj("shard_ip_1", "postgresql://dsn1"))]
        ]
    )
    router = FakeDatabaseRouter([session])
    resolver = TenantShardResolver(db_router=router, app_slug="ip", ttl_secs=300)

    # 1. First resolution should query global DB session
    shard_id, shard_dsn = await resolver.resolve_shard("ten_1")
    assert shard_id == "shard_ip_1"
    assert shard_dsn == "postgresql://dsn1"
    assert len(session.calls) == 1

    # 2. Second resolution must hit in-memory cache without needing another session
    shard_id_cached, shard_dsn_cached = await resolver.resolve_shard("ten_1")
    assert shard_id_cached == "shard_ip_1"
    assert shard_dsn_cached == "postgresql://dsn1"
    assert len(session.calls) == 1  # No additional DB call


@pytest.mark.asyncio
async def test_tenant_shard_resolver_not_found_raises() -> None:
    session = FakeSession(execute_results=[[]])
    router = FakeDatabaseRouter([session])
    resolver = TenantShardResolver(db_router=router, app_slug="ip", ttl_secs=300)

    with pytest.raises(TenantNotFoundError, match="Tenant ten_missing not found in Global DB"):
        await resolver.resolve_shard("ten_missing")

    # Inherits from ValueError for backward compatibility
    with pytest.raises(ValueError):
        await resolver.resolve_shard("ten_missing")


@pytest.mark.asyncio
async def test_tenant_shard_resolver_cache_expiry() -> None:
    session1 = FakeSession(
        execute_results=[
            [(FakeTenantObj("ten_1"), FakeShardObj("shard_ip_1", "postgresql://dsn1"))]
        ]
    )
    session2 = FakeSession(
        execute_results=[
            [(FakeTenantObj("ten_1"), FakeShardObj("shard_ip_1", "postgresql://dsn1_updated"))]
        ]
    )
    router = FakeDatabaseRouter([session1, session2])
    # Very short TTL
    resolver = TenantShardResolver(db_router=router, app_slug="ip", ttl_secs=0.01)

    shard_id, shard_dsn = await resolver.resolve_shard("ten_1")
    assert shard_id == "shard_ip_1"
    assert shard_dsn == "postgresql://dsn1"

    # Wait for TTL to expire
    time.sleep(0.02)

    shard_id2, shard_dsn2 = await resolver.resolve_shard("ten_1")
    assert shard_id2 == "shard_ip_1"
    assert shard_dsn2 == "postgresql://dsn1_updated"


@pytest.mark.asyncio
async def test_tenant_shard_resolver_lru_eviction() -> None:
    session1 = FakeSession(execute_results=[[(FakeTenantObj("t1"), FakeShardObj("s1", "dsn1"))]])
    session2 = FakeSession(execute_results=[[(FakeTenantObj("t2"), FakeShardObj("s2", "dsn2"))]])
    session3 = FakeSession(execute_results=[[(FakeTenantObj("t3"), FakeShardObj("s3", "dsn3"))]])
    router = FakeDatabaseRouter([session1, session2, session3])
    # Limit max entries to 2
    resolver = TenantShardResolver(db_router=router, app_slug="ip", ttl_secs=300, max_entries=2)

    await resolver.resolve_shard("t1")
    await resolver.resolve_shard("t2")
    assert len(resolver._cache) == 2

    # Resolving t3 should evict the oldest entry (t1)
    await resolver.resolve_shard("t3")
    assert len(resolver._cache) == 2
    assert "t1" not in resolver._cache
    assert "t2" in resolver._cache
    assert "t3" in resolver._cache


@pytest.mark.asyncio
async def test_tenant_shard_resolver_get_all_tenant_ids() -> None:
    session = FakeSession(execute_results=[["ten_1", "ten_2", "ten_3"]])
    router = FakeDatabaseRouter([session])
    resolver = TenantShardResolver(db_router=router, app_slug="ip", ttl_secs=300)

    tenant_ids = await resolver.get_all_tenant_ids()
    assert tenant_ids == ["ten_1", "ten_2", "ten_3"]


@pytest.mark.asyncio
async def test_cellular_resolver_resolves_endpoint_with_reader_dsn_and_write_fence() -> None:
    s_active = FakeShardObj(
        "ucp_shard_01",
        "dsn://pod01/writer",
        name="pod01",
        reader_dsn="dsn://pod01/reader",
        status="write_fenced",
    )
    session = FakeSession(execute_results=[[s_active]])
    router = FakeDatabaseRouter([session])
    resolver = TenantShardResolver(db_router=router, app_slug="edi", ttl_secs=300)

    assert resolver.app_slug == "edi"
    outcome = await resolver.resolve_tenant_endpoint("iam_ten_01")
    assert outcome.status == ShardResolutionStatus.WRITE_FENCED
    assert outcome.endpoint is not None
    assert outcome.endpoint.writer_dsn == "dsn://pod01/writer"
    assert outcome.endpoint.reader_dsn == "dsn://pod01/reader"

    cached = await resolver.resolve_tenant_endpoint("iam_ten_01")
    assert cached.status == ShardResolutionStatus.WRITE_FENCED
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_cellular_resolver_uses_virtual_bucket_ring_for_subjects() -> None:
    cell_a = FakeShardObj(
        "ucp_shard_cell_a",
        "dsn://cell_a/writer",
        reader_dsn="dsn://cell_a/reader",
        routing_strategy="virtual_bucket_ring",
    )
    cell_b = FakeShardObj(
        "ucp_shard_cell_b",
        "dsn://cell_b/writer",
        reader_dsn="dsn://cell_b/reader",
        routing_strategy="virtual_bucket_ring",
    )
    b1 = FakeBucketAssignmentObj("ucp_bkt_1", "ucp_app_1", 0, 2047, "ucp_shard_cell_a")
    b2 = FakeBucketAssignmentObj("ucp_bkt_2", "ucp_app_1", 2048, 4095, "ucp_shard_cell_b")

    session = FakeSession(execute_results=[[(b1, cell_a), (b2, cell_b)]])
    router = FakeDatabaseRouter([session])
    resolver = TenantShardResolver(db_router=router, app_slug="consumer", ttl_secs=300)

    out1 = await resolver.resolve_subject_endpoint("iam_ten_global", "usr_alpha_1")
    out2 = await resolver.resolve_subject_endpoint("iam_ten_global", "usr_beta_2")
    assert out1.status == ShardResolutionStatus.RESOLVED
    assert out2.status == ShardResolutionStatus.RESOLVED
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_cellular_resolver_caches_empty_ring_assignments() -> None:
    # First global session: empty bucket assignments
    ring_session = FakeSession(execute_results=[[]])
    # Second global session: tenant shard registry lookup
    shard_obj = FakeShardObj(
        "ucp_shard_01",
        "dsn://pod01/writer",
        name="pod01",
        reader_dsn="dsn://pod01/reader",
    )
    tenant_session = FakeSession(execute_results=[[shard_obj]])
    router = FakeDatabaseRouter([ring_session, tenant_session])
    resolver = TenantShardResolver(db_router=router, app_slug="consumer", ttl_secs=300)

    out1 = await resolver.resolve_subject_endpoint("iam_ten_01", "usr_1")
    assert out1.status == ShardResolutionStatus.RESOLVED
    assert out1.endpoint is not None
    assert out1.endpoint.shard_id == "ucp_shard_01"

    # Second call should use cached empty ring and cached endpoint without hitting router sessions
    out2 = await resolver.resolve_subject_endpoint("iam_ten_01", "usr_2")
    assert out2.status == ShardResolutionStatus.RESOLVED
    assert len(router._sessions) == 0


@pytest.mark.asyncio
async def test_cellular_resolver_invalid_ring_topology_returns_not_found() -> None:
    cell_a = FakeShardObj("ucp_shard_cell_a", "dsn://cell_a/writer")
    # Incomplete range: 0..1000 does not cover 4096 buckets
    b_incomplete = FakeBucketAssignmentObj("ucp_bkt_1", "ucp_app_1", 0, 1000, "ucp_shard_cell_a")
    session = FakeSession(execute_results=[[(b_incomplete, cell_a)]])
    router = FakeDatabaseRouter([session])
    resolver = TenantShardResolver(db_router=router, app_slug="consumer", ttl_secs=300)

    out1 = await resolver.resolve_subject_endpoint("iam_ten_global", "usr_1")
    assert out1.status == ShardResolutionStatus.NOT_FOUND
    assert out1.reason == "ring_topology_invalid"

    # Second call within TTL should return cached outcome without raising or extra session pops
    out2 = await resolver.resolve_subject_endpoint("iam_ten_global", "usr_2")
    assert out2.status == ShardResolutionStatus.NOT_FOUND
    assert out2.reason == "ring_topology_invalid"
