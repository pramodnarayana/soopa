from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from identity.application.authenticate_use_case import TenantNotProvisionedError
from identity.domain.identity_context import TokenClaims
from identity.domain.models.user import User
from identity.ports.outbound.token_verifier_port import TokenVerifierPort

from ucp.application.use_cases.authenticators.jwt_strategy import JwtStrategy
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
    # Setup Fake DB
    tenant = Tenant(
        id="ten_123",
        name="Test",
        slug="test",
        idp_tenant_id="idp_org_456",
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await fake_tenant_repo.save(tenant)

    user = User(
        id="usr_123",
        email="test@test.com",
        name="Test User",
        idp_user_id="idp_usr_456",
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await fake_user_repo.save(user)

    # Mock Token Verifier to return an IdentityContext with IdP IDs
    mock_token_verifier.verify.return_value = TokenClaims(
        sub="idp_usr_456",
        iss="https://zitadel",
        aud="test",
        exp=9999999999,
        tenant_id="idp_org_456",
        authorized_tenants={"idp_org_456"},
    )

    # Execute
    # authenticate_bearer_token calls verifier and constructs basic IdentityContext
    identity = await jwt_strategy.authenticate("mock_token")

    # Assert mappings occurred
    assert identity.tenant_id == "ten_123"
    assert identity.subject == "usr_123"
    assert "ten_123" in identity.authorized_tenants
    assert "idp_org_456" in identity.authorized_tenants  # Keeps original
    assert identity.tenant_mapping["idp_org_456"] == "ten_123"


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
    # Test when the token ALREADY has canonical IDs (starts with ten_ / usr_)
    mock_token_verifier.verify.return_value = TokenClaims(
        sub="usr_789",
        iss="https://zitadel",
        aud="test",
        exp=9999999999,
        tenant_id="ten_789",
        authorized_tenants={"ten_789"},
    )

    identity = await jwt_strategy.authenticate("mock_token")

    # No DB lookup needed, passes straight through
    assert identity.tenant_id == "ten_789"
    assert identity.subject == "usr_789"
    assert "ten_789" in identity.authorized_tenants


@pytest.mark.asyncio
async def test_jwt_strategy_resolves_dynamic_capabilities(
    jwt_strategy, fake_role_repo, mock_token_verifier
):
    mock_token_verifier.verify.return_value = TokenClaims(
        sub="usr_999",
        iss="https://zitadel",
        aud="test",
        exp=9999999999,
        tenant_id="ten_999",
        authorized_tenants={"ten_999"},
    )

    # Setup Fake DB to return capabilities when get_user_capabilities is called
    from unittest.mock import AsyncMock

    fake_role_repo.get_user_capabilities = AsyncMock(
        side_effect=lambda tenant_id, user_id: (
            {"cap:read"} if tenant_id == "ten_999" else {"cap:global"}
        )
    )

    identity = await jwt_strategy.authenticate("mock_token")

    assert "cap:read" in identity.capabilities
    assert "cap:global" in identity.capabilities
