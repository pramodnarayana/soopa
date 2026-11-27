"""Narrow PostgreSQL 16 integration tests for ltree hierarchy, external_identities, ReBAC, & entitlements."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from database.models.identity import (
    Role as OrmRole,
)
from database.models.identity import (
    Tenant as OrmTenant,
)
from database.models.identity import (
    TenantUser as OrmTenantUser,
)
from database.models.identity import (
    User as OrmUser,
)
from database.models.identity import (
    UserRole as OrmUserRole,
)
from database.models.subscriptions import App as OrmApp
from database.models.subscriptions import AppSubscription as OrmAppSubscription
from seedwork.utils import generate_id
from sqlalchemy.ext.asyncio import AsyncSession
from ucp.adapters.outbound.database.tenant_entitlement_repository import (
    SqlAlchemyTenantEntitlementRepository,
)

from identity.adapters.outbound.cache.in_memory_global_authz_catalog import (
    InMemoryGlobalAuthzCatalog,
)
from identity.adapters.outbound.cache.l1_lru_principal_cache import L1LruPrincipalCache
from identity.adapters.outbound.database.authz_directory_repository import (
    SqlAlchemyAuthzDirectoryRepository,
)
from identity.adapters.outbound.database.external_identity_repository import (
    SqlAlchemyExternalIdentityRepository,
)
from identity.adapters.outbound.database.resource_grant_repository import (
    SqlAlchemyResourceGrantRepository,
)
from identity.application.authorize_use_case import HybridLocalAuthorizationEngine
from identity.domain.constants import (
    ActorType,
    AuthzEffect,
    AuthzReasonCode,
    MembershipScope,
    MembershipStatus,
    ResourceSubjectType,
    TenantIsolationMode,
    TenantTierType,
)
from identity.domain.dtos import AuthzRequest, PrincipalContext, ResourceContext, ResourceGrantDTO
from identity.domain.identity_context import PLATFORM_TENANT_ID

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_postgres_ltree_hierarchy_external_identities_rebac_and_entitlements(
    db_session: AsyncSession,
) -> None:
    """Exercises real PostgreSQL 16 ltree, covering indexes, ReBAC grants, and UCP entitlement inversion."""
    now = datetime.now(UTC)
    partner_id = generate_id("ten")
    org_id = generate_id("ten")
    ws_id = generate_id("ten")
    user_id = generate_id("iam_usr")
    role_id = generate_id("iam_rol")
    app_id = generate_id("app")
    app_slug = f"ip_{app_id[-6:]}"

    db_session.add_all(
        [
            OrmTenant(
                id=partner_id,
                parent_tenant_id=PLATFORM_TENANT_ID,
                hierarchy_path=f"{PLATFORM_TENANT_ID}.{partner_id}",
                tier_type=TenantTierType.PARTNER.value,
                isolation_mode=TenantIsolationMode.POOLED_REALM.value,
                name=f"Partner {partner_id}",
                slug=f"partner-{partner_id}",
                status="active",
            ),
            OrmTenant(
                id=org_id,
                parent_tenant_id=partner_id,
                hierarchy_path=f"{PLATFORM_TENANT_ID}.{partner_id}.{org_id}",
                tier_type=TenantTierType.ORGANIZATION.value,
                isolation_mode=TenantIsolationMode.POOLED_REALM.value,
                name=f"Org {org_id}",
                slug=f"org-{org_id}",
                status="active",
            ),
            OrmTenant(
                id=ws_id,
                parent_tenant_id=org_id,
                hierarchy_path=f"{PLATFORM_TENANT_ID}.{partner_id}.{org_id}.{ws_id}",
                tier_type=TenantTierType.WORKSPACE.value,
                isolation_mode=TenantIsolationMode.POOLED_REALM.value,
                name=f"Workspace {ws_id}",
                slug=f"ws-{ws_id}",
                status="active",
            ),
            OrmUser(
                id=user_id,
                email=f"{user_id}@example.com",
                name="Postgres Integration User",
                status="active",
                tokens_valid_after=now - timedelta(minutes=10),
            ),
            OrmApp(id=app_id, slug=app_slug, name="Dynamic Test App"),
        ]
    )
    await db_session.flush()

    db_session.add(
        OrmRole(
            id=role_id,
            tenant_id=partner_id,
            name=f"PartnerReader_{role_id[-6:]}",
            capabilities=["ip:flows:read"],
            deny_capabilities=[],
        )
    )
    await db_session.flush()

    db_session.add_all(
        [
            OrmTenantUser(
                user_id=user_id,
                tenant_id=partner_id,
                scope=MembershipScope.SUBTREE.value,
                status=MembershipStatus.ACTIVE.value,
                active=True,
            ),
            OrmUserRole(
                id=generate_id("iam_usr_rol"),
                tenant_id=partner_id,
                user_id=user_id,
                role_id=role_id,
            ),
            OrmAppSubscription(tenant_id=ws_id, app_id=app_id, status="active"),
        ]
    )
    await db_session.flush()

    # 1. Verify composite (idp_issuer, idp_subject) external_identities persistence & idempotency
    ext_repo = SqlAlchemyExternalIdentityRepository(db_session)
    link1 = await ext_repo.link_identity(
        user_id=user_id,
        idp_issuer="http://localhost:8080",
        idp_subject=f"casdoor-sub-{user_id}",
        idp_realm_name="soopa-global",
    )
    link2 = await ext_repo.link_identity(
        user_id=user_id,
        idp_issuer="http://localhost:8080",
        idp_subject=f"casdoor-sub-{user_id}",
        idp_realm_name="soopa-global",
    )
    assert link1.id == link2.id
    resolved = await ext_repo.find_by_issuer_subject(
        idp_issuer="http://localhost:8080",
        idp_subject=f"casdoor-sub-{user_id}",
    )
    assert resolved is not None and resolved.user_id == user_id

    # 2. Verify ReBAC ResourceGrant covering-index lookup
    grant_repo = SqlAlchemyResourceGrantRepository(db_session)
    await grant_repo.save_grant(
        ResourceGrantDTO(
            id=generate_id("iam_grt"),
            tenant_id=ws_id,
            resource_type="stitch",
            resource_id="stch_pg_01",
            relation="editor",
            subject_type=ResourceSubjectType.USER,
            subject_id=user_id,
            effect=AuthzEffect.ALLOW,
        )
    )

    # 3. End-to-end 4-Layer Local PDP backed by real Postgres ltree + UCP TenantEntitlementPort
    engine = HybridLocalAuthorizationEngine(
        directory=SqlAlchemyAuthzDirectoryRepository(db_session),
        global_catalog=InMemoryGlobalAuthzCatalog(),
        entitlements=SqlAlchemyTenantEntitlementRepository(db_session),
        cache=L1LruPrincipalCache(),
        resource_grants=grant_repo,
    )
    principal = PrincipalContext(
        user_id=user_id,
        idp_issuer="http://localhost:8080",
        idp_subject=f"casdoor-sub-{user_id}",
        actor_type=ActorType.HUMAN,
        token_issued_at=now,
        email=f"{user_id}@example.com",
        email_verified=True,
        idp_realm="soopa-global",
    )

    # Inherited Partner SUBTREE read reaches L3 Workspace + passes UCP subscription check!
    dec_read = await engine.evaluate(
        AuthzRequest(
            principal=principal, app_slug=app_slug, action="ip:flows:read", tenant_id=ws_id, now=now
        )
    )
    assert dec_read.is_allowed
    assert dec_read.reason_code == AuthzReasonCode.ALLOWED_BY_CAPABILITY

    # ReBAC resource grant unlocks write on stch_pg_01 inside L3 Workspace!
    dec_write = await engine.evaluate(
        AuthzRequest(
            principal=principal,
            app_slug=app_slug,
            action="ip:flows:write",
            tenant_id=ws_id,
            resource=ResourceContext(
                resource_type="stitch", resource_id="stch_pg_01", tenant_id=ws_id
            ),
            now=now,
        )
    )
    assert dec_write.is_allowed
    assert dec_write.reason_code == AuthzReasonCode.ALLOWED_BY_RESOURCE_GRANT

    # Unsubscribed app is blocked cleanly at Layer 1!
    dec_unsub = await engine.evaluate(
        AuthzRequest(
            principal=principal,
            app_slug="unsubscribed_app",
            action="ip:flows:read",
            tenant_id=ws_id,
            now=now,
        )
    )
    assert not dec_unsub.is_allowed
    assert dec_unsub.reason_code == AuthzReasonCode.DENIED_APP_NOT_SUBSCRIBED
