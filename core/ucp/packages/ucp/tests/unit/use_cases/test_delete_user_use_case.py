from datetime import UTC, datetime

import pytest
from identity.domain.constants import UserStatus
from identity.domain.models.user import User

from ucp.application.use_cases.delete_user_use_case import DeleteUserCommand, DeleteUserUseCase
from ucp.domain.exceptions import ResourceNotFoundError
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def fake_uow():
    return FakeUcpUnitOfWork()


@pytest.fixture
def delete_user_use_case(fake_uow):
    return DeleteUserUseCase(uow=fake_uow)


@pytest.mark.asyncio
async def test_delete_user_success(fake_uow, delete_user_use_case):
    # Setup User
    user = User(
        id="iam_usr_123",
        email="test@example.com",
        name="Test User",
        idp_user_id="idp_usr_123",
        status=UserStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await fake_uow.user_repo.save(user)

    # Establish fake membership so find_by_id_and_tenant works
    fake_uow.user_repo.tenant_memberships.add(("iam_ten_123", "iam_usr_123"))
    # Also add it to role repo so has_any_tenant_memberships works
    fake_uow.role_repo.user_roles.append(("iam_ten_123", "iam_usr_123", "iam_rol_abc"))

    command = DeleteUserCommand(
        tenant_id="iam_ten_123",
        user_id="iam_usr_123",
    )

    await delete_user_use_case.execute(command)

    # Verify user was deleted from tenant
    assert ("iam_ten_123", "iam_usr_123") not in fake_uow.role_repo.user_roles

    # Since it was their only membership, user should be deleted from DB completely
    saved_user = await fake_uow.user_repo.find_by_id("iam_usr_123")
    assert saved_user is None


@pytest.mark.asyncio
async def test_delete_user_not_found(delete_user_use_case):
    command = DeleteUserCommand(
        tenant_id="iam_ten_unknown",
        user_id="iam_usr_unknown",
    )

    with pytest.raises(ResourceNotFoundError) as exc:
        await delete_user_use_case.execute(command)
    assert "User iam_usr_unknown not found" in str(exc.value)
