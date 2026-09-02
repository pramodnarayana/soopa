from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from identity.application.authenticate_use_case import TenantNotProvisionedError
from identity.domain.constants import IdentityIdPrefix, UserStatus
from identity.domain.identity_context import TokenClaims
from identity.domain.models.user import User
from identity.ports.outbound.token_verifier_port import TokenVerifierPort
from seedwork.utils import generate_id

from ucp.application.use_cases.authenticators.jwt_strategy import JwtStrategy
from ucp.domain.constants import LifecycleStatus
from ucp.domain.models.tenant import Tenant
from ucp.testing.fakes import FakeRoleRepository, FakeTenantRepository, FakeUserRepository


@pytest.fixture
def fake_tenant_repo():
    return FakeTenantRepository()


@pytest.fixture
def fake_user_repo():
    return FakeUserRepository()


@pytest.fixture
def fake_role_repo():
    return FakeRoleRepository()


@pytest.fixture
def mock_token_verifier():
    verifier = AsyncMock(spec=TokenVerifierPort)
    return verifier


@pytest.fixture
def jwt_strategy(fake_tenant_repo, fake_user_repo, fake_role_repo, mock_token_verifier):
    @asynccontextmanager
    async def tenant_repo_factory():
        yield fake_tenant_repo

    @asynccontextmanager
    async def user_repo_factory():
        yield fake_user_repo

    @asynccontextmanager
    async def role_repo_factory():
        yield fake_role_repo

    return JwtStrategy(
        tenant_repo_factory=tenant_repo_factory,
        user_repo_factory=user_repo_factory,
        role_repo_factory=role_repo_factory,
        token_verifier=mock_token_verifier,
    )


@pytest.mark.asyncio
async def test_jwt_strategy_resolves_idp_ids(
    jwt_strategy, fake_tenant_repo, fake_user_repo, mock_token_verifier
):
    # Generate canonical IDs — these represent our local DB records
    canonical_tenant_id = generate_id(IdentityIdPrefix.TENANT)
    canonical_user_id = generate_id(IdentityIdPrefix.USER)
    # IdP IDs are external, opaque strings — not domain-prefixed
    idp_org_id = "idp_org_456"
    idp_user_id = "idp_usr_456"

    tenant = Tenant(
        id=canonical_tenant_id,
        name="Test",
        slug="test",
        idp_tenant_id=idp_org_id,
        status=LifecycleStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await fake_tenant_repo.save(tenant)

    user = User(
        id=canonical_user_id,
        email="test@test.com",
        name="Test User",
        idp_user_id=idp_user_id,
        status=UserStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await fake_user_repo.save(user)

    mock_token_verifier.verify.return_value = TokenClaims(
        sub=idp_user_id,
        iss="https://zitadel",
        aud="test",
        exp=9999999999,
        tenant_id=idp_org_id,
        authorized_tenants={idp_org_id},
    )

    identity = await jwt_strategy.authenticate("mock_token")

    assert identity.tenant_id == canonical_tenant_id
    assert identity.subject == canonical_user_id
    assert canonical_tenant_id in identity.authorized_tenants
    assert idp_org_id in identity.authorized_tenants  # Keeps original
    assert identity.tenant_mapping[idp_org_id] == canonical_tenant_id


@pytest.mark.asyncio
async def test_jwt_strategy_raises_if_tenant_not_provisioned(jwt_strategy, mock_token_verifier):
    mock_token_verifier.verify.return_value = TokenClaims(
        sub="idp_usr_456",
        iss="https://zitadel",
        aud="test",
        exp=9999999999,
        tenant_id="idp_org_unknown",
        authorized_tenants={"idp_org_unknown"},
    )

    with pytest.raises(TenantNotProvisionedError) as exc:
        await jwt_strategy.authenticate("mock_token")

    assert "idp_org_unknown" in str(exc.value)


@pytest.mark.asyncio
async def test_jwt_strategy_handles_canonical_ids(
    jwt_strategy, fake_tenant_repo, fake_user_repo, mock_token_verifier
):
    # Token already has canonical iam_ IDs — strategy must pass straight through
    canonical_tenant_id = generate_id(IdentityIdPrefix.TENANT)
    canonical_user_id = generate_id(IdentityIdPrefix.USER)

    mock_token_verifier.verify.return_value = TokenClaims(
        sub=canonical_user_id,
        iss="https://zitadel",
        aud="test",
        exp=9999999999,
        tenant_id=canonical_tenant_id,
        authorized_tenants={canonical_tenant_id},
    )

    identity = await jwt_strategy.authenticate("mock_token")

    assert identity.tenant_id == canonical_tenant_id
    assert identity.subject == canonical_user_id
    assert canonical_tenant_id in identity.authorized_tenants


@pytest.mark.asyncio
async def test_jwt_strategy_resolves_dynamic_capabilities(
    jwt_strategy, fake_role_repo, mock_token_verifier
):
    canonical_tenant_id = generate_id(IdentityIdPrefix.TENANT)
    canonical_user_id = generate_id(IdentityIdPrefix.USER)

    mock_token_verifier.verify.return_value = TokenClaims(
        sub=canonical_user_id,
        iss="https://zitadel",
        aud="test",
        exp=9999999999,
        tenant_id=canonical_tenant_id,
        authorized_tenants={canonical_tenant_id},
    )

    fake_role_repo.get_user_capabilities = AsyncMock(
        side_effect=lambda tenant_id, user_id: (
            {"cap:read"} if tenant_id == canonical_tenant_id else {"cap:global"}
        )
    )

    identity = await jwt_strategy.authenticate("mock_token")

    assert "cap:read" in identity.capabilities
    assert "cap:global" in identity.capabilities
