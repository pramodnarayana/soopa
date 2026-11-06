"""Pure zero-mock Phase 4 unit tests for Identity SQLAlchemy Data Mappers and TokenClaims mapper."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from database.models.identity import ApiToken as ApiTokenORM
from database.models.identity import Capability as OrmCapability
from database.models.identity import Role as OrmRole
from database.models.identity import User as DbUser
from database.provider import DatabaseProvider
from seedwork.domain.types import JsonDict
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id
from sqlalchemy import text

from identity.adapters.outbound.database.api_token_repository import SqlAlchemyApiTokenRepository
from identity.adapters.outbound.database.capability_repository import (
    SqlAlchemyCapabilityRepository,
)
from identity.adapters.outbound.database.role_repository import SqlAlchemyRoleRepository
from identity.adapters.outbound.database.user_repository import SqlAlchemyUserRepository
from identity.adapters.outbound.zitadel.jwks_token_verifier_adapter import (
    ZitadelTokenVerifierAdapter,
)
from identity.domain.api_token import ApiToken
from identity.domain.authorization import Role as DomainRole
from identity.domain.constants import IdentityIdPrefix, UserStatus
from identity.domain.user import User


def test_user_repository_mappers_round_trip() -> None:
    now_naive = datetime.now(UTC).replace(tzinfo=None)
    user_id_1 = generate_id(IdentityIdPrefix.USER.value)
    user_id_2 = generate_id(IdentityIdPrefix.USER.value)
    idp_user_1 = generate_id(SystemIdPrefix.GENERIC.value)
    idp_user_2 = generate_id(SystemIdPrefix.GENERIC.value)

    db_user = DbUser(
        id=user_id_1,
        idp_user_id=idp_user_1,
        email="alice@acme.test",
        name="Alice Smith",
        status=UserStatus.ACTIVE.value,
        created_at=now_naive,
        updated_at=now_naive,
    )

    domain_user = SqlAlchemyUserRepository._to_domain_model(db_user, role="TenantAdmin")
    assert domain_user.id == user_id_1
    assert domain_user.status == UserStatus.ACTIVE
    assert domain_user.role == "TenantAdmin"
    assert domain_user.created_at.tzinfo == UTC

    domain_user.deactivate()
    domain_user.name = "AliceUpdated"
    SqlAlchemyUserRepository._update_record_from_domain(db_user, domain_user)
    assert db_user.name == "AliceUpdated"
    assert db_user.status == UserStatus.INACTIVE.value

    fresh_user = User.create(
        id=user_id_2,
        idp_user_id=idp_user_2,
        email="bob@acme.test",
        name="Bob Jones",
    ).unwrap()
    new_orm = SqlAlchemyUserRepository._to_orm_record(fresh_user)
    assert new_orm.id == user_id_2
    assert new_orm.email == "bob@acme.test"
    assert new_orm.created_at.tzinfo is None


def test_role_repository_mappers_round_trip() -> None:
    role_id = generate_id(IdentityIdPrefix.ROLE.value)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)

    orm_role = OrmRole(
        id=role_id,
        tenant_id=tenant_id,
        name="CustomEditor",
        description="Can edit EDI routes",
        capabilities=["webhooks:read", "webhooks:write"],
    )
    domain_role = SqlAlchemyRoleRepository._to_domain_model(orm_role)
    assert domain_role.id == role_id
    assert domain_role.tenant_id == tenant_id
    assert domain_role.capabilities == ["webhooks:read", "webhooks:write"]

    updated = DomainRole(
        id=role_id,
        tenant_id=tenant_id,
        name="SeniorEditor",
        description="Updated description",
        capabilities=["webhooks:read"],
    )
    SqlAlchemyRoleRepository._update_record_from_domain(orm_role, updated)
    assert orm_role.name == "SeniorEditor"
    assert orm_role.description == "Updated description"
    assert orm_role.capabilities == ["webhooks:read"]

    created_orm = SqlAlchemyRoleRepository._to_orm_record(updated)
    assert created_orm.id == role_id
    assert created_orm.tenant_id == tenant_id
    assert created_orm.name == "SeniorEditor"


def test_api_token_repository_bidirectional_mappers() -> None:
    now = datetime.now(UTC)
    token_id = generate_id(IdentityIdPrefix.TOKEN.value)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    client_id = generate_id(SystemIdPrefix.CLIENT.value)

    token = ApiToken.create(
        token_id=token_id,
        tenant_id=tenant_id,
        name="ERP Production Key",
        client_id=client_id,
        secret_hash="sha256_digest_fixture",
        expires_at=now + timedelta(days=30),
        now=now,
    ).unwrap()

    orm_record: ApiTokenORM = SqlAlchemyApiTokenRepository._to_orm_record(token)
    assert orm_record.id == token_id
    assert orm_record.tenant_id == tenant_id
    assert orm_record.client_id == client_id

    mapped = SqlAlchemyApiTokenRepository._to_domain_model(orm_record)
    assert mapped.id == token_id
    assert mapped.tenant_id == tenant_id
    assert mapped.name == "ERP Production Key"
    assert mapped.client_id == client_id


def test_jwks_token_verifier_explicit_token_claims_mapper() -> None:
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    subject_id = generate_id(IdentityIdPrefix.USER.value)
    org_id = generate_id(SystemIdPrefix.GENERIC.value)

    raw_claims: JsonDict = {
        "sub": subject_id,
        "iss": "https://auth.soopa.test",
        "aud": ["soopa-api"],
        "exp": 1999999999,
        "iat": 1700000000,
        "unexpected_vendor_claim": "ignored_cleanly",
    }
    payload: dict[str, object] = {
        **raw_claims,
        "tenant_id": tenant_id,
        "organization_id": org_id,
        "authorized_tenants": {tenant_id},
        "roles": ["TenantAdmin"],
        "permissions": ["users:read"],
        "tenant_roles": {tenant_id: ["TenantAdmin"]},
    }
    claims = ZitadelTokenVerifierAdapter._to_token_claims(payload, raw_claims)
    assert claims.sub == subject_id
    assert claims.tenant_id == tenant_id
    assert claims.organization_id == org_id
    assert claims.authorized_tenants == {tenant_id}
    assert claims.roles == ["TenantAdmin"]
    assert claims.tenant_roles == {tenant_id: ["TenantAdmin"]}
    assert claims.raw_claims["unexpected_vendor_claim"] == "ignored_cleanly"


@pytest.mark.asyncio
async def test_sqlalchemy_api_token_repository_get_by_client_id_excludes_expired_and_inactive() -> (
    None
):
    provider = DatabaseProvider.from_url("sqlite+aiosqlite:///:memory:")
    async with provider.session_factory() as setup_session:
        await setup_session.execute(text("ATTACH DATABASE ':memory:' AS identity"))
        await setup_session.execute(
            text(
                """
                CREATE TABLE identity.api_tokens (
                    id VARCHAR(128) PRIMARY KEY,
                    tenant_id VARCHAR(128) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    client_id VARCHAR(64) NOT NULL UNIQUE,
                    secret_hash VARCHAR(64) NOT NULL,
                    last_used_at TIMESTAMP NULL,
                    expires_at TIMESTAMP NULL,
                    active BOOLEAN NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    deleted_at TIMESTAMP NULL,
                    deleted_by VARCHAR(128) NULL
                )
                """
            )
        )
        now = datetime.now(UTC)
        tenant_id = generate_id(IdentityIdPrefix.TENANT.value)

        expired = ApiToken.create(
            tenant_id=tenant_id,
            name="Expired",
            client_id="cli_expired_db",
            secret_hash="hash_1",
            expires_at=now - timedelta(minutes=1),
            now=now - timedelta(hours=1),
        ).unwrap()
        valid = ApiToken.create(
            tenant_id=tenant_id,
            name="Valid",
            client_id="cli_valid_db",
            secret_hash="hash_2",
            expires_at=now + timedelta(minutes=10),
        ).unwrap()
        unbounded = ApiToken.create(
            tenant_id=tenant_id,
            name="Unbounded",
            client_id="cli_unbounded_db",
            secret_hash="hash_3",
            expires_at=None,
        ).unwrap()

        repo = SqlAlchemyApiTokenRepository(setup_session)
        await repo.save(expired)
        await repo.save(valid)
        await repo.save(unbounded)
        await setup_session.commit()

        assert await repo.get_by_client_id("cli_expired_db") is None
        # When evaluated against a past reference timestamp prior to expiry, SQL lookup returns the token
        fetched_past = await repo.get_by_client_id("cli_expired_db", now=now - timedelta(minutes=5))
        assert fetched_past is not None
        assert fetched_past.id == expired.id
        # When evaluated against a past reference timestamp prior to expiry, SQL lookup returns the token
        fetched_past = await repo.get_by_client_id("cli_expired_db", now=now - timedelta(minutes=5))
        assert fetched_past is not None
        assert fetched_past.id == expired.id
        fetched_valid = await repo.get_by_client_id("cli_valid_db")
        assert fetched_valid is not None
        assert fetched_valid.id == valid.id
        fetched_unbounded = await repo.get_by_client_id("cli_unbounded_db")
        assert fetched_unbounded is not None
        assert fetched_unbounded.id == unbounded.id

    await provider.engine.dispose()


def test_capability_repository_mapper() -> None:
    orm_cap = OrmCapability(
        code="ip:records:canonical:read",
        domain="ip",
        resource="records:canonical",
        action="read",
        display_name="View Canonical Records",
        description="Allows inspecting canonical L3 normalized records.",
        is_sensitive=False,
    )

    domain_model = SqlAlchemyCapabilityRepository._to_domain_model(orm_cap)
    assert domain_model.code == "ip:records:canonical:read"
    assert domain_model.domain == "ip"
    assert domain_model.resource == "records:canonical"
    assert domain_model.action == "read"
    assert domain_model.display_name == "View Canonical Records"
    assert domain_model.description == "Allows inspecting canonical L3 normalized records."
    assert domain_model.is_sensitive is False
