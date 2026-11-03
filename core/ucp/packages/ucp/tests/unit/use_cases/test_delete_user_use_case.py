from datetime import UTC, datetime

import pytest
from identity.domain.constants import UserStatus
from identity.domain.user import User
from seedwork.utils import generate_id

from ucp.application.use_cases.delete_user_use_case import DeleteUserCommand, DeleteUserUseCase
from ucp.domain.constants import UcpIdPrefix as DomainIdPrefix
from ucp.domain.exceptions import UcpErrorCode
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def fake_uow() -> FakeUcpUnitOfWork:
    return FakeUcpUnitOfWork()


@pytest.fixture
def delete_user_use_case(fake_uow: FakeUcpUnitOfWork) -> DeleteUserUseCase:
    return DeleteUserUseCase(uow=fake_uow)


@pytest.mark.asyncio
async def test_delete_user_success(
    fake_uow: FakeUcpUnitOfWork, delete_user_use_case: DeleteUserUseCase
) -> None:
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    user_id = generate_id(DomainIdPrefix.USER)
    role_id = generate_id(DomainIdPrefix.ROLE)

    user = User(
        id=user_id,
        email="test@example.com",
        name="Test User",
        idp_user_id="idp_usr_123",
        status=UserStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await fake_uow.user_repo.save(user)

    fake_uow.user_repo.tenant_memberships.add((tenant_id, user_id))
    fake_uow.role_repo.user_roles.append((tenant_id, user_id, role_id))

    command = DeleteUserCommand(
        tenant_id=tenant_id,
        user_id=user_id,
    )

    res = await delete_user_use_case.execute(command)
    assert res.is_ok

    assert (tenant_id, user_id) not in fake_uow.role_repo.user_roles

    saved_user = await fake_uow.user_repo.find_by_id(user_id)
    assert saved_user is None


@pytest.mark.asyncio
async def test_delete_user_not_found(delete_user_use_case: DeleteUserUseCase) -> None:
    missing_user_id = generate_id(DomainIdPrefix.USER)
    command = DeleteUserCommand(
        tenant_id=generate_id(DomainIdPrefix.TENANT),
        user_id=missing_user_id,
    )

    res = await delete_user_use_case.execute(command)
    assert res.is_err
    err = res.unwrap_err()
    assert err.code == UcpErrorCode.USER_NOT_FOUND
    assert missing_user_id in err.message
