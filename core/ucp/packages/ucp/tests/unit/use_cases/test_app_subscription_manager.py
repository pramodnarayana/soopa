from contextlib import asynccontextmanager

import pytest
from seedwork.utils import generate_id

from ucp.adapters.outbound.database.least_loaded_shard_allocator import (
    LeastLoadedPooledShardStrategy,
)
from ucp.application.dto.shard_allocation import ShardCandidateDTO
from ucp.application.use_cases.app_subscription_manager import AppSubscriptionManager
from ucp.domain.app import App
from ucp.domain.constants import LifecycleStatus, UcpEventType
from ucp.domain.constants import UcpIdPrefix as DomainIdPrefix
from ucp.ports.outbound.ucp_event_consumer_port import UcpEventMessage
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def fake_uow():
    return FakeUcpUnitOfWork()


@pytest.fixture
def shard_allocator():
    return LeastLoadedPooledShardStrategy()


@pytest.fixture
def provisioner(fake_uow, shard_allocator):
    @asynccontextmanager
    async def fake_factory():
        yield fake_uow

    return AppSubscriptionManager(
        uow_factory=fake_factory,
        shard_allocator=shard_allocator,
    )


@pytest.mark.asyncio
async def test_handle_app_subscribed_success(provisioner, fake_uow):
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    app_id = generate_id(DomainIdPrefix.UCP_APP)

    app = App(id=app_id, name="EDI", description="EDI App", slug="edi")
    fake_uow.app_repo.apps.append(app)

    event = UcpEventMessage(
        id=generate_id(DomainIdPrefix.TOKEN),
        tenant_id=tenant_id,
        event_type=UcpEventType.APP_SUBSCRIBED.value,
        payload={"app_id": app_id},
    )

    await provisioner.handle_app_subscribed(event)

    assert fake_uow.committed is True
    assert fake_uow.tenant_repo.subscriptions.get((tenant_id, app_id)) == LifecycleStatus.ACTIVE
    assert (tenant_id, app_id, "edi_shard_1") in fake_uow.tenant_repo.allocations


@pytest.mark.asyncio
async def test_handle_app_subscribed_dynamic_allocation_any_app(provisioner, fake_uow):
    """Verifies that ANY arbitrary app (e.g. billing, ip, iot) is allocated dynamically."""
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    app_id = generate_id(DomainIdPrefix.UCP_APP)

    # Completely arbitrary app
    app = App(id=app_id, name="Billing", description="Billing App", slug="billing")
    fake_uow.app_repo.apps.append(app)
    fake_uow.tenant_repo.candidate_shards = [
        ShardCandidateDTO(
            shard_id="billing_shard_east_01",
            shard_name="Billing East Shard",
            current_tenant_count=0,
            status="active",
        )
    ]

    event = UcpEventMessage(
        id=generate_id(DomainIdPrefix.TOKEN),
        tenant_id=tenant_id,
        event_type=UcpEventType.APP_SUBSCRIBED.value,
        payload={"app_id": app_id},
    )

    await provisioner.handle_app_subscribed(event)

    assert fake_uow.committed is True
    assert fake_uow.tenant_repo.subscriptions.get((tenant_id, app_id)) == LifecycleStatus.ACTIVE
    assert (tenant_id, app_id, "billing_shard_east_01") in fake_uow.tenant_repo.allocations


@pytest.mark.asyncio
async def test_handle_app_subscribed_idempotency_guard(provisioner, fake_uow):
    """Verifies that duplicate app.subscribed events preserve the original shard without reallocating."""
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    app_id = generate_id(DomainIdPrefix.UCP_APP)

    app = App(id=app_id, name="IP", description="IP App", slug="ip")
    fake_uow.app_repo.apps.append(app)
    fake_uow.tenant_repo.candidate_shards = [
        ShardCandidateDTO(
            shard_id="ip_shard_1",
            shard_name="IP Shard 1",
            current_tenant_count=10,
            status="active",
        ),
        ShardCandidateDTO(
            shard_id="ip_shard_2",
            shard_name="IP Shard 2",
            current_tenant_count=0,
            status="active",
        ),
    ]

    # Pre-existing allocation on ip_shard_1
    fake_uow.tenant_repo.allocations.append((tenant_id, app_id, "ip_shard_1"))

    event = UcpEventMessage(
        id=generate_id(DomainIdPrefix.TOKEN),
        tenant_id=tenant_id,
        event_type=UcpEventType.APP_SUBSCRIBED.value,
        payload={"app_id": app_id},
    )

    await provisioner.handle_app_subscribed(event)

    # Should retain ip_shard_1 even though ip_shard_2 has 0 tenants!
    effective_shard = await fake_uow.tenant_repo.get_allocated_shard(tenant_id, app_id)
    assert effective_shard == "ip_shard_1"


@pytest.mark.asyncio
async def test_handle_app_subscribed_exhausted_shards_rolls_back(provisioner, fake_uow):
    """Verifies that missing or exhausted shards roll back the transaction cleanly."""
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    app_id = generate_id(DomainIdPrefix.UCP_APP)

    app = App(id=app_id, name="Custom", description="Custom App", slug="custom")
    fake_uow.app_repo.apps.append(app)
    # Zero candidate shards
    fake_uow.tenant_repo.candidate_shards = []

    event = UcpEventMessage(
        id=generate_id(DomainIdPrefix.TOKEN),
        tenant_id=tenant_id,
        event_type=UcpEventType.APP_SUBSCRIBED.value,
        payload={"app_id": app_id},
    )

    with pytest.raises(RuntimeError, match="Shard allocation failed"):
        await provisioner.handle_app_subscribed(event)

    assert fake_uow.rolled_back is True


@pytest.mark.asyncio
async def test_handle_app_unsubscribed_success(provisioner, fake_uow):
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    app_id = generate_id(DomainIdPrefix.UCP_APP)

    app = App(id=app_id, name="EDI", description="EDI App", slug="edi")
    fake_uow.app_repo.apps.append(app)

    event = UcpEventMessage(
        id=generate_id(DomainIdPrefix.TOKEN),
        tenant_id=tenant_id,
        event_type=UcpEventType.APP_UNSUBSCRIBED.value,
        payload={"app_id": app_id},
    )

    await provisioner.handle_app_unsubscribed(event)

    assert fake_uow.committed is True
    assert fake_uow.tenant_repo.subscriptions.get((tenant_id, app_id)) == LifecycleStatus.INACTIVE


@pytest.mark.asyncio
async def test_handle_app_resubscription_reactivates_retained_shard(provisioner, fake_uow):
    """Verifies that resubscribing after unsubscription reactivates the tenant's retained shard."""
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    app_id = generate_id(DomainIdPrefix.UCP_APP)

    app = App(id=app_id, name="IP", description="IP App", slug="ip")
    fake_uow.app_repo.apps.append(app)
    fake_uow.tenant_repo.candidate_shards = [
        ShardCandidateDTO(
            shard_id="ip_shard_1",
            shard_name="IP Shard 1",
            current_tenant_count=10,
            status="active",
        ),
        ShardCandidateDTO(
            shard_id="ip_shard_2",
            shard_name="IP Shard 2",
            current_tenant_count=0,
            status="active",
        ),
    ]

    # Pre-existing allocation on ip_shard_1, but marked INACTIVE due to prior unsubscription
    fake_uow.tenant_repo.allocations.append((tenant_id, app_id, "ip_shard_1"))
    fake_uow.tenant_repo.shard_statuses[(tenant_id, app_id)] = LifecycleStatus.INACTIVE.value

    # Prior to resubscription, active allocated shard is None
    assert await fake_uow.tenant_repo.get_allocated_shard(tenant_id, app_id) is None

    event = UcpEventMessage(
        id=generate_id(DomainIdPrefix.TOKEN),
        tenant_id=tenant_id,
        event_type=UcpEventType.APP_SUBSCRIBED.value,
        payload={"app_id": app_id},
    )

    await provisioner.handle_app_subscribed(event)

    # Should reactivate ip_shard_1 rather than allocating ip_shard_2
    assert fake_uow.committed is True
    effective_shard = await fake_uow.tenant_repo.get_allocated_shard(tenant_id, app_id)
    assert effective_shard == "ip_shard_1"
    assert (
        fake_uow.tenant_repo.shard_statuses.get((tenant_id, app_id)) == LifecycleStatus.ACTIVE.value
    )


@pytest.mark.asyncio
async def test_handle_app_resubscription_fails_if_retained_shard_decommissioned(
    provisioner, fake_uow
):
    """Verifies that resubscription fails explicitly if the retained shard was decommissioned."""
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    app_id = generate_id(DomainIdPrefix.UCP_APP)

    app = App(id=app_id, name="IP", description="IP App", slug="ip")
    fake_uow.app_repo.apps.append(app)
    # Only ip_shard_2 is active; retained ip_shard_1 is decommissioned/missing
    fake_uow.tenant_repo.candidate_shards = [
        ShardCandidateDTO(
            shard_id="ip_shard_2",
            shard_name="IP Shard 2",
            current_tenant_count=0,
            status="active",
        ),
    ]

    fake_uow.tenant_repo.allocations.append((tenant_id, app_id, "ip_shard_1"))
    fake_uow.tenant_repo.shard_statuses[(tenant_id, app_id)] = LifecycleStatus.INACTIVE.value

    event = UcpEventMessage(
        id=generate_id(DomainIdPrefix.TOKEN),
        tenant_id=tenant_id,
        event_type=UcpEventType.APP_SUBSCRIBED.value,
        payload={"app_id": app_id},
    )

    with pytest.raises(RuntimeError, match="cannot be reactivated without data migration"):
        await provisioner.handle_app_subscribed(event)

    assert fake_uow.rolled_back is True
    assert fake_uow.tenant_repo.shard_statuses.get((tenant_id, app_id)) == LifecycleStatus.INACTIVE
