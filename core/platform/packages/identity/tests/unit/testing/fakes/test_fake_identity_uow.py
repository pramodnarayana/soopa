from datetime import UTC, datetime

import pytest

from identity.domain.identity_context import PLATFORM_TENANT_ID
from identity.domain.models.api_token import ApiTokenDomainModel
from identity.domain.models.authorization import Role
from identity.domain.models.user import User
from identity.testing.fakes.fake_identity_uow import (
    FakeApiTokenRepository,
    FakeRoleRepository,
    FakeUserRepository,
)


def _user(user_id: str) -> User:
    now = datetime.now(UTC)
    return User(
        id=user_id,
        idp_user_id=None,
        email=f"{user_id}@example.com",
        name=user_id,
        status="active",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_fake_user_repository_filters_by_tenant_membership() -> None:
    repo = FakeUserRepository()
    first_user = _user("iam_usr_first")
    second_user = _user("iam_usr_second")
    repo.users.extend((first_user, second_user))
    repo.tenant_memberships.update(
        {
            ("iam_ten_first", first_user.id),
            ("iam_ten_second", second_user.id),
            (PLATFORM_TENANT_ID, first_user.id),
        }
    )

    assert await repo.find_users_by_tenant("iam_ten_first") == [first_user]
    assert await repo.find_by_id_and_tenant(first_user.id, "iam_ten_first") is first_user
    assert await repo.find_by_id_and_tenant(first_user.id, "iam_ten_second") is None
    assert await repo.has_any_tenant_memberships(first_user.id) is True


@pytest.mark.asyncio
async def test_fake_role_repository_normalizes_platform_tenant() -> None:
    repo = FakeRoleRepository()
    role = Role(
        id="role_platform",
        tenant_id=PLATFORM_TENANT_ID,
        name="PlatformAdmin",
        description=None,
        capabilities=["platform:admin"],
    )
    repo.roles.append(role)

    await repo.assign_user_role(None, "iam_usr_platform", role.id)

    assert repo.user_roles[(PLATFORM_TENANT_ID, "iam_usr_platform")] == [role.id]
    assert await repo.get_user_capabilities(None, "iam_usr_platform") == {"platform:admin"}


@pytest.mark.asyncio
async def test_fake_api_token_lookup_excludes_inactive_tokens() -> None:
    repo = FakeApiTokenRepository()
    now = datetime.now(UTC)
    inactive_token = ApiTokenDomainModel(
        id="iam_tok_inactive",
        tenant_id="iam_ten_first",
        name="Inactive",
        client_id="client_inactive",
        secret_hash="hash",
        last_used_at=None,
        expires_at=None,
        active=False,
        created_at=now,
        updated_at=now,
    )
    repo.tokens.append(inactive_token)

    assert await repo.get_by_client_id(inactive_token.client_id) is None
