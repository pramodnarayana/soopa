from datetime import UTC, datetime, timedelta

import pytest

from identity.domain.api_token import ApiToken
from identity.domain.authorization import Role
from identity.domain.constants import UserStatus
from identity.domain.identity_context import PLATFORM_TENANT_ID
from identity.domain.user import User
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
        status=UserStatus.ACTIVE,
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
    inactive_token = ApiToken(
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

    expired_token = ApiToken(
        id="iam_tok_expired",
        tenant_id="iam_ten_first",
        name="Expired",
        client_id="client_expired",
        secret_hash="hash",
        last_used_at=None,
        expires_at=now - timedelta(seconds=1),
        active=True,
        created_at=now - timedelta(hours=1),
        updated_at=now - timedelta(hours=1),
    )
    valid_token = ApiToken(
        id="iam_tok_valid",
        tenant_id="iam_ten_first",
        name="Valid",
        client_id="client_valid",
        secret_hash="hash",
        last_used_at=None,
        expires_at=now + timedelta(hours=1),
        active=True,
        created_at=now,
        updated_at=now,
    )
    repo.tokens.extend((expired_token, valid_token))

    assert await repo.get_by_client_id(expired_token.client_id) is None
    assert (
        await repo.get_by_client_id(expired_token.client_id, now=now - timedelta(minutes=1))
        is expired_token
    )
    assert await repo.get_by_client_id(valid_token.client_id) is valid_token
