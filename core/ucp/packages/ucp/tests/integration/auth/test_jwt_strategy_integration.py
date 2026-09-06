from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from identity.adapters.outbound.database.role_repository import PostgresRoleRepository
from identity.adapters.outbound.database.user_repository import PostgresUserRepository
from identity.application.authenticate_use_case import TenantNotProvisionedError
from identity.domain.constants import IdentityIdPrefix, UserStatus
from identity.domain.identity_context import TokenClaims
from identity.domain.models.user import User
from identity.ports.outbound.token_verifier_port import TokenVerifierPort
from seedwork.utils import generate_id

from ucp.adapters.outbound.database.tenant_repository import TenantRepository
from ucp.application.use_cases.authenticators.jwt_strategy import JwtStrategy
from ucp.domain.constants import LifecycleStatus
from ucp.domain.models.tenant import Tenant

pytestmark = pytest.mark.integration


class FakeTokenVerifier(TokenVerifierPort):
    def __init__(self, claims: TokenClaims):
        self.claims = claims

    async def verify(self, token: str) -> TokenClaims:
        return self.claims


@pytest.fixture
def jwt_strategy(db_session):
    @asynccontextmanager
    async def tenant_repo_factory():
        yield TenantRepository(db_session)

    @asynccontextmanager
    async def user_repo_factory():
        yield PostgresUserRepository(db_session)

    @asynccontextmanager
    async def role_repo_factory():
        yield PostgresRoleRepository(db_session)

    def _create_strategy(claims: TokenClaims) -> JwtStrategy:
        return JwtStrategy(
            tenant_repo_factory=tenant_repo_factory,
            user_repo_factory=user_repo_factory,
            role_repo_factory=role_repo_factory,
            token_verifier=FakeTokenVerifier(claims),
        )

    return _create_strategy


@pytest.mark.asyncio
async def test_jwt_strategy_resolves_idp_ids(jwt_strategy, db_session):
    # Generate canonical IDs
    canonical_tenant_id = generate_id(IdentityIdPrefix.TENANT)
    canonical_user_id = generate_id(IdentityIdPrefix.USER)

    idp_org_id = "idp_org_456"
    idp_user_id = "idp_usr_456"

    tenant_repo = TenantRepository(db_session)
    tenant = Tenant(
        id=canonical_tenant_id,
        name="Test",
        slug=f"test-{canonical_tenant_id}",
        idp_tenant_id=idp_org_id,
        status=LifecycleStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await tenant_repo.save(tenant)

    user_repo = PostgresUserRepository(db_session)
    user = User(
        id=canonical_user_id,
        email="test@test.com",
        name="Test User",
        idp_user_id=idp_user_id,
        status=UserStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await user_repo.save(user)
    await db_session.flush()

    strategy = jwt_strategy(
        TokenClaims(
            sub=idp_user_id,
            iss="https://zitadel",
            aud="test",
            exp=9999999999,
            tenant_id=idp_org_id,
            roles=["admin"],
        )
    )

    identity = await strategy.authenticate("mock_token")

    assert identity.subject == canonical_user_id
    assert identity.tenant_id == canonical_tenant_id
    assert canonical_tenant_id in identity.authorized_tenants


@pytest.mark.asyncio
async def test_jwt_strategy_raises_if_tenant_not_provisioned(jwt_strategy, db_session):
    idp_org_id = "unprovisioned_org"

    strategy = jwt_strategy(
        TokenClaims(
            sub="idp_usr",
            iss="https://zitadel",
            aud="test",
            exp=9999999999,
            tenant_id=idp_org_id,
            authorized_tenants={idp_org_id},
            roles=[],
        )
    )

    with pytest.raises(TenantNotProvisionedError):
        await strategy.authenticate("mock_token")


@pytest.mark.asyncio
async def test_jwt_strategy_passes_unmapped_claims(jwt_strategy, db_session):
    # If the user has a claim but it's not a platform organization, it should map properly.
    idp_user_id = "idp_usr_789"

    user_repo = PostgresUserRepository(db_session)
    user = User(
        id=generate_id(IdentityIdPrefix.USER),
        email="test2@test.com",
        name="Test User",
        idp_user_id=idp_user_id,
        status=UserStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await user_repo.save(user)
    await db_session.flush()

    strategy = jwt_strategy(
        TokenClaims(
            sub=idp_user_id,
            iss="https://zitadel",
            aud="test",
            exp=9999999999,
            tenant_id=None,
            roles=[],
        )
    )

    identity = await strategy.authenticate("mock_token")

    assert identity.tenant_id is None
