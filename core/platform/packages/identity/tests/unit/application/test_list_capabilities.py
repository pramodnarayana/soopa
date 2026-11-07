import pytest
from seedwork.domain.exceptions import Result

from identity.application.list_capabilities_use_case import (
    ListCapabilitiesQuery,
    ListCapabilitiesUseCase,
)
from identity.domain.authorization import CapabilityDescriptor
from identity.testing.fakes.fake_identity_uow import (
    FakeCapabilityRepository,
    FakeIdentityUnitOfWork,
)


@pytest.fixture
def uow() -> FakeIdentityUnitOfWork:
    sample_capabilities = [
        CapabilityDescriptor(
            code="ip:records:canonical:read",
            domain="ip",
            resource="records:canonical",
            action="read",
            display_name="View Canonical Records",
            description="Allows inspecting canonical L3 normalized records.",
            is_sensitive=False,
        ),
        CapabilityDescriptor(
            code="ip:records:raw:read",
            domain="ip",
            resource="records:raw",
            action="read",
            display_name="View Raw Records",
            description="Allows inspecting L1 raw wire and L2 replicas.",
            is_sensitive=True,
        ),
        CapabilityDescriptor(
            code="identity:users:read",
            domain="identity",
            resource="users",
            action="read",
            display_name="View Users",
            description="Allows viewing tenant users.",
            is_sensitive=False,
        ),
    ]
    work_unit = FakeIdentityUnitOfWork()
    work_unit.capability_repo = FakeCapabilityRepository(sample_capabilities)
    return work_unit


@pytest.mark.asyncio
async def test_list_all_capabilities(uow: FakeIdentityUnitOfWork) -> None:
    use_case = ListCapabilitiesUseCase(uow)
    result = await use_case.execute(ListCapabilitiesQuery())

    assert isinstance(result, Result)
    assert result.is_ok
    capabilities = result.unwrap()
    assert len(capabilities) == 3
    assert [c.code for c in capabilities] == [
        "identity:users:read",
        "ip:records:canonical:read",
        "ip:records:raw:read",
    ]


@pytest.mark.asyncio
async def test_list_capabilities_filtered_by_domain(uow: FakeIdentityUnitOfWork) -> None:
    use_case = ListCapabilitiesUseCase(uow)
    result = await use_case.execute(ListCapabilitiesQuery(domain="ip"))

    assert result.is_ok
    capabilities = result.unwrap()
    assert len(capabilities) == 2
    assert all(c.domain == "ip" for c in capabilities)


@pytest.mark.asyncio
async def test_list_capabilities_non_existent_domain(uow: FakeIdentityUnitOfWork) -> None:
    use_case = ListCapabilitiesUseCase(uow)
    result = await use_case.execute(ListCapabilitiesQuery(domain="non_existent"))

    assert result.is_ok
    assert len(result.unwrap()) == 0
