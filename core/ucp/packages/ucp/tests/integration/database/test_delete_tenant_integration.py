import pytest
from identity.domain.user import User
from seedwork.utils import generate_id

from ucp.application.use_cases.delete_tenant_use_case import DeleteTenantUseCase
from ucp.bootstrap.container import create_ucp_uow
from ucp.domain.constants import UcpIdPrefix as DomainIdPrefix
from ucp.domain.exceptions import UcpErrorCode
from ucp.domain.tenant import Tenant

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_delete_tenant_not_found(db_session):
    uow = create_ucp_uow(db_session)
    delete_use_case = DeleteTenantUseCase(uow=uow)

    res = await delete_use_case.execute(generate_id(DomainIdPrefix.TENANT))
    assert res.is_err
    assert res.unwrap_err().code == UcpErrorCode.TENANT_NOT_FOUND


@pytest.mark.asyncio
async def test_delete_tenant_success(db_session):
    uow = create_ucp_uow(db_session)
    delete_use_case = DeleteTenantUseCase(uow=uow)

    tenant_id = generate_id(DomainIdPrefix.TENANT)
    user_id = generate_id(DomainIdPrefix.USER)

    tenant = Tenant.create(
        id=tenant_id,
        name="Test",
        slug="test-del",
        idp_tenant_id="zitadel-org-123",
        subscriptions=[],
    ).unwrap()

    async with uow:
        await uow.tenant_repo.save(tenant)
        await uow.commit()

    fake_user = User.create(
        id=user_id, idp_user_id="zitadel-user-1", email="test@test.com", name="Test User"
    ).unwrap()

    async with uow:
        await uow.user_repo.save(fake_user)
        await uow.commit()

    res = await delete_use_case.execute(tenant_id, "idemp-key")
    assert res.is_ok

    async with uow:
        deleted_tenant = await uow.tenant_repo.find_by_id(tenant_id)
        assert deleted_tenant is None
