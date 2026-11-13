import pytest

from ucp.adapters.outbound.database.least_loaded_shard_allocator import (
    LeastLoadedPooledShardStrategy,
)
from ucp.application.dto.shard_allocation import (
    ShardAllocationErrorCode,
    ShardCandidateDTO,
)
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def fake_uow():
    return FakeUcpUnitOfWork()


@pytest.mark.asyncio
async def test_idempotency_returns_existing_shard(fake_uow):
    tenant_id = "ten_123"
    app_id = "app_edi"
    fake_uow.tenant_repo.candidate_shards = [
        ShardCandidateDTO(
            shard_id="edi_shard_99",
            shard_name="Existing Shard",
            current_tenant_count=1,
            status="active",
        )
    ]
    fake_uow.tenant_repo.allocations.append((tenant_id, app_id, "edi_shard_99"))

    allocator = LeastLoadedPooledShardStrategy()
    result = await allocator.allocate_shard_for_app(fake_uow, tenant_id, app_id, "edi")

    assert result.is_ok
    assert result.unwrap() == "edi_shard_99"


@pytest.mark.asyncio
async def test_retained_shard_decommissioned_returns_error(fake_uow):
    tenant_id = "ten_123"
    app_id = "app_edi"
    # Retained shard is edi_shard_99, but candidate pool only has edi_shard_1
    fake_uow.tenant_repo.candidate_shards = [
        ShardCandidateDTO(
            shard_id="edi_shard_1",
            shard_name="EDI Shard 1",
            current_tenant_count=1,
            status="active",
        )
    ]
    fake_uow.tenant_repo.allocations.append((tenant_id, app_id, "edi_shard_99"))

    allocator = LeastLoadedPooledShardStrategy()
    result = await allocator.allocate_shard_for_app(fake_uow, tenant_id, app_id, "edi")

    assert result.is_err
    err = result.unwrap_err()
    assert err.code == ShardAllocationErrorCode.NO_ACTIVE_SHARDS
    assert "cannot be reactivated without data migration" in err.message


@pytest.mark.asyncio
async def test_single_candidate_chosen(fake_uow):
    tenant_id = "ten_123"
    app_id = "app_ip"
    fake_uow.tenant_repo.candidate_shards = [
        ShardCandidateDTO(
            shard_id="ip_shard_1",
            shard_name="IP Shard 1",
            current_tenant_count=5,
            status="active",
        )
    ]

    allocator = LeastLoadedPooledShardStrategy()
    result = await allocator.allocate_shard_for_app(fake_uow, tenant_id, app_id, "ip")

    assert result.is_ok
    assert result.unwrap() == "ip_shard_1"


@pytest.mark.asyncio
async def test_p2c_selects_lesser_loaded_shard(fake_uow):
    tenant_id = "ten_123"
    app_id = "app_ip"
    fake_uow.tenant_repo.candidate_shards = [
        ShardCandidateDTO(
            shard_id="ip_shard_1",
            shard_name="IP Shard 1",
            current_tenant_count=100,
            status="active",
        ),
        ShardCandidateDTO(
            shard_id="ip_shard_2",
            shard_name="IP Shard 2",
            current_tenant_count=2,
            status="active",
        ),
    ]

    # Deterministic sample selector returning [shard_1, shard_2]
    def sample_selector(candidates, _k):
        return [candidates[0], candidates[1]]

    allocator = LeastLoadedPooledShardStrategy(sample_selector=sample_selector)
    result = await allocator.allocate_shard_for_app(fake_uow, tenant_id, app_id, "ip")

    assert result.is_ok
    assert result.unwrap() == "ip_shard_2"


@pytest.mark.asyncio
async def test_no_active_candidates_returns_error(fake_uow):
    tenant_id = "ten_123"
    app_id = "app_unknown"
    fake_uow.tenant_repo.candidate_shards = []

    allocator = LeastLoadedPooledShardStrategy()
    result = await allocator.allocate_shard_for_app(fake_uow, tenant_id, app_id, "nonexistent")

    assert result.is_err
    err = result.unwrap_err()
    assert err.code == ShardAllocationErrorCode.NO_ACTIVE_SHARDS
    assert "nonexistent" in err.message
