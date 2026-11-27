from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from identity.adapters.outbound.database.role_repository import SqlAlchemyRoleRepository
from identity.adapters.outbound.database.user_repository import SqlAlchemyUserRepository
from identity.application.authenticate_use_case import TenantNotProvisionedError
from identity.domain.constants import TenantIsolationMode, UserStatus
from identity.domain.identity_context import PLATFORM_TENANT_ID, TokenClaims
from identity.domain.user import User
from identity.ports.outbound.token_verifier_port import TokenVerifierPort
from seedwork.utils import generate_id

from ucp.adapters.outbound.database.tenant_repository import SqlAlchemyTenantRepository
from ucp.application.use_cases.authenticators.jwt_strategy import JwtStrategy
from ucp.domain.constants import LifecycleStatus
from ucp.domain.constants import UcpIdPrefix as DomainIdPrefix
from ucp.domain.tenant import Tenant

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
        yield SqlAlchemyTenantRepository(db_session)

    @asynccontextmanager
    async def user_repo_factory():
        yield SqlAlchemyUserRepository(db_session)

    @asynccontextmanager
    async def role_repo_factory():
        yield SqlAlchemyRoleRepository(db_session)

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
    canonical_tenant_id = generate_id(DomainIdPrefix.TENANT)
    canonical_user_id = generate_id(DomainIdPrefix.USER)

    idp_org_id = "idp_org_456"
    idp_user_id = "idp_usr_456"

    tenant_repo = SqlAlchemyTenantRepository(db_session)
    tenant = Tenant(
        id=canonical_tenant_id,
        name="Test",
        slug=f"test-{canonical_tenant_id}",
        idp_realm_name=idp_org_id,
        isolation_mode=TenantIsolationMode.DEDICATED_IDP_ORG,
        status=LifecycleStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await tenant_repo.save(tenant)

    user_repo = SqlAlchemyUserRepository(db_session)
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

    identity = await strategy.authenticate("fake_token")

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
        await strategy.authenticate("fake_token")


@pytest.mark.asyncio
async def test_jwt_strategy_raises_if_primary_tenant_is_not_provisioned(jwt_strategy, db_session):
    idp_org_id = "unprovisioned_primary_org"
    strategy = jwt_strategy(
        TokenClaims(
            sub="idp_usr",
            iss="https://zitadel",
            aud="test",
            exp=9999999999,
            tenant_id=idp_org_id,
            authorized_tenants=set(),
            roles=[],
        )
    )

    with pytest.raises(TenantNotProvisionedError, match=idp_org_id):
        await strategy.authenticate("fake_token")


@pytest.mark.asyncio
async def test_jwt_strategy_passes_unmapped_claims(jwt_strategy, db_session):
    # If the user has a claim but it's not a platform organization, it should map properly.
    idp_user_id = "idp_usr_789"

    user_repo = SqlAlchemyUserRepository(db_session)
    user = User(
        id=generate_id(DomainIdPrefix.USER),
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

    identity = await strategy.authenticate("fake_token")

    assert identity.tenant_id is None


@pytest.mark.asyncio
async def test_jwt_strategy_platform_admin_with_sentinel_tenant_mapping(jwt_strategy, db_session):
    idp_org_id = "400262792403222531"
    idp_user_id = "admin_user_123"

    user_repo = SqlAlchemyUserRepository(db_session)
    user = User(
        id=generate_id(DomainIdPrefix.USER),
        email=f"admin_{idp_user_id}@flowwolf.io",
        name="Platform Admin",
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
            tenant_id=PLATFORM_TENANT_ID,
            authorized_tenants={PLATFORM_TENANT_ID},
            tenant_roles={PLATFORM_TENANT_ID: ["PlatformAdmin"]},
            tenant_mapping={idp_org_id: PLATFORM_TENANT_ID},
            roles=["PlatformAdmin"],
        )
    )

    identity = await strategy.authenticate("fake_token")

    assert identity.tenant_id == PLATFORM_TENANT_ID
    assert PLATFORM_TENANT_ID in identity.authorized_tenants
    assert identity.is_platform_admin is True
    assert identity.tenant_mapping[idp_org_id] == PLATFORM_TENANT_ID


@pytest.mark.asyncio
async def test_jwt_strategy_premapped_tenant_skips_database_lookup(jwt_strategy, db_session):
    # If the token verifier adapter pre-mapped an IdP org to a canonical ID,
    # JwtStrategy resolves it from identity.tenant_mapping without querying the database.
    idp_org_id = "idp_custom_org_456"
    canonical_id = "ten_custom_resolved"

    strategy = jwt_strategy(
        TokenClaims(
            sub="user_abc",
            iss="https://zitadel",
            aud="test",
            exp=9999999999,
            tenant_id=idp_org_id,
            authorized_tenants={idp_org_id},
            tenant_mapping={idp_org_id: canonical_id},
            roles=[],
        )
    )

    identity = await strategy.authenticate("fake_token")

    assert identity.tenant_id == canonical_id
    assert canonical_id in identity.authorized_tenants
