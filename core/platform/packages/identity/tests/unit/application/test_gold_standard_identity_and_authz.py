"""Zero-mock unit tests for IdP-Agnostic Identity, 4-Layer Local PDP, Multi-Tier Hierarchy, & OIDC."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import httpx
import jwt
from config_sync.domain.dtos import ConfigDeltaEvent
from config_sync.domain.enums import ConfigChangeAction
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from shttp import HttpClient

from identity.adapters.outbound.cache.in_memory_global_authz_catalog import (
    InMemoryGlobalAuthzCatalog,
)
from identity.adapters.outbound.cache.l1_lru_principal_cache import L1LruPrincipalCache
from identity.adapters.outbound.config_sync.identity_invalidation_sink import (
    IdentityInvalidationSink,
)
from identity.adapters.outbound.oidc.oidc_jwks_token_verifier_adapter import (
    OidcJwksTokenVerifierAdapter,
    OidcTokenVerifierOptions,
)
from identity.application.authorize_use_case import HybridLocalAuthorizationEngine
from identity.application.jit_provision_user_use_case import (
    JitProvisionUserCommand,
    JitProvisionUserUseCase,
)
from identity.domain.authorization import Capability, CapabilityDescriptor
from identity.domain.constants import (
    IDENTITY_CONFIG_APP_ID,
    ActorType,
    AuthzEffect,
    AuthzObligation,
    AuthzReasonCode,
    IdentityConfigEntityType,
    MembershipScope,
    MembershipStatus,
    PolicyEngineType,
    ResourceSubjectType,
    TenantIsolationMode,
    TenantTierType,
    UserStatus,
)
from identity.domain.dtos import (
    AuthzRequest,
    EmailDomainRouteDTO,
    ExternalIdentityDTO,
    MembershipDTO,
    PolicyRuleDTO,
    PrincipalContext,
    PrincipalSnapshotDTO,
    ResourceContext,
    ResourceGrantDTO,
    RoleDefinitionDTO,
    TenantNodeDTO,
    TrustedIssuerDTO,
    UserRoleAssignmentDTO,
)
from identity.domain.exceptions import IdentityErrorCode
from identity.domain.hierarchy import (
    build_hierarchy_path,
    detect_hierarchy_cycle,
    validate_ltree_label,
)
from identity.domain.identity_context import PLATFORM_TENANT_ID
from identity.domain.user import User
from identity.ports.outbound.external_identity_repository_port import (
    ExternalIdentityRepositoryPort,
)
from identity.ports.outbound.resource_grant_repository_port import ResourceGrantRepositoryPort
from identity.ports.outbound.tenant_entitlement_port import TenantEntitlementPort
from identity.ports.outbound.tenant_hierarchy_port import AuthzDirectoryPort
from identity.ports.outbound.user_repository_port import UserRepositoryPort

_EPOCH_ZERO = datetime(1970, 1, 1, tzinfo=UTC)


class _FakeDirectory(AuthzDirectoryPort):
    def __init__(self) -> None:
        self.principals: dict[str, PrincipalSnapshotDTO] = {}
        self.tenants: dict[str, TenantNodeDTO] = {}
        self.roles: dict[str, RoleDefinitionDTO] = {}

    async def get_principal_snapshot(self, *, user_id: str) -> PrincipalSnapshotDTO | None:
        return self.principals.get(user_id)

    async def get_tenant_ancestor_chain(self, *, tenant_id: str) -> tuple[TenantNodeDTO, ...]:
        leaf = self.tenants.get(tenant_id)
        if leaf is None:
            return ()
        segs = leaf.hierarchy_path.split(".")
        return tuple(self.tenants[s] for s in segs if s in self.tenants)

    async def get_roles_by_ids(self, *, role_ids: Sequence[str]) -> dict[str, RoleDefinitionDTO]:
        return {rid: self.roles[rid] for rid in role_ids if rid in self.roles}


class _FakeEntitlements(TenantEntitlementPort):
    def __init__(self, mapping: dict[str, frozenset[str]]) -> None:
        self.mapping = mapping

    async def get_enabled_app_slugs(self, *, tenant_id: str) -> frozenset[str]:
        return self.mapping.get(tenant_id, frozenset())

    async def is_app_enabled(self, *, tenant_id: str, app_slug: str) -> bool:
        return app_slug.lower() in self.mapping.get(tenant_id, frozenset())


class _FakeResourceGrants(ResourceGrantRepositoryPort):
    def __init__(self) -> None:
        self.grants: list[ResourceGrantDTO] = []

    async def find_matching_grants(
        self,
        *,
        tenant_id: str,
        resource_type: str,
        resource_id: str,
        user_id: str,
        role_ids: Sequence[str],
    ) -> tuple[ResourceGrantDTO, ...]:
        out: list[ResourceGrantDTO] = []
        for g in self.grants:
            matches_resource = (
                g.tenant_id == tenant_id
                and g.resource_type == resource_type
                and g.resource_id == resource_id
            )
            matches_subject = (
                g.subject_type == ResourceSubjectType.USER and g.subject_id == user_id
            ) or (g.subject_type == ResourceSubjectType.ROLE and g.subject_id in role_ids)
            if matches_resource and matches_subject:
                out.append(g)
        return tuple(out)

    async def save_grant(self, grant: ResourceGrantDTO) -> ResourceGrantDTO:
        self.grants.append(grant)
        return grant

    async def revoke_grant(self, *, tenant_id: str, grant_id: str) -> bool:
        before = len(self.grants)
        self.grants = [
            g for g in self.grants if not (g.tenant_id == tenant_id and g.id == grant_id)
        ]
        return len(self.grants) < before

    async def list_grants_for_resource(
        self, *, tenant_id: str, resource_type: str, resource_id: str
    ) -> tuple[ResourceGrantDTO, ...]:
        return tuple(
            g
            for g in self.grants
            if g.tenant_id == tenant_id
            and g.resource_type == resource_type
            and g.resource_id == resource_id
        )


class _FakeExternalIdentities(ExternalIdentityRepositoryPort):
    def __init__(self) -> None:
        self.by_key: dict[tuple[str, str], ExternalIdentityDTO] = {}

    async def find_by_issuer_subject(
        self, *, idp_issuer: str, idp_subject: str
    ) -> ExternalIdentityDTO | None:
        return self.by_key.get((idp_issuer.rstrip("/"), idp_subject))

    async def list_for_user(self, *, user_id: str) -> tuple[ExternalIdentityDTO, ...]:
        return tuple(v for v in self.by_key.values() if v.user_id == user_id)

    async def link_identity(
        self,
        *,
        user_id: str,
        idp_issuer: str,
        idp_subject: str,
        idp_realm_name: str | None = None,
    ) -> ExternalIdentityDTO:
        dto = ExternalIdentityDTO(
            id=f"iam_ext_{len(self.by_key) + 1}",
            user_id=user_id,
            idp_issuer=idp_issuer.rstrip("/"),
            idp_subject=idp_subject,
            idp_realm_name=idp_realm_name,
            linked_at=datetime.now(UTC),
        )
        self.by_key[(dto.idp_issuer, dto.idp_subject)] = dto
        return dto


class _FakeUserRepo(UserRepositoryPort):
    def __init__(self) -> None:
        self.by_id: dict[str, User] = {}

    async def save(self, user: User) -> None:
        self.by_id[user.id] = user

    async def find_by_id(self, user_id: str) -> User | None:
        return self.by_id.get(user_id)

    async def find_by_email(self, email: str) -> User | None:
        lowered = email.strip().lower()
        for u in self.by_id.values():
            if u.email.lower() == lowered:
                return u
        return None

    async def find_by_idp_user_id(self, idp_user_id: str) -> User | None:
        for u in self.by_id.values():
            if u.idp_user_id == idp_user_id:
                return u
        return None

    async def delete(self, user: User) -> None:
        self.by_id.pop(user.id, None)

    async def find_all_by_tenant(self, tenant_id: str) -> list[User]:
        del tenant_id
        return list(self.by_id.values())


def test_ltree_label_validation_and_cycle_detection() -> None:
    assert validate_ltree_label("ten_acme_01").is_ok
    bad = validate_ltree_label("ten-invalid-hyphen")
    assert bad.is_err
    assert bad.unwrap_err().code == IdentityErrorCode.INVALID_HIERARCHY_LABEL

    path_res = build_hierarchy_path(parent_path=PLATFORM_TENANT_ID, tenant_id="ten_partner_1")
    assert path_res.is_ok
    assert path_res.unwrap() == f"{PLATFORM_TENANT_ID}.ten_partner_1"

    cycle_res = build_hierarchy_path(
        parent_path=f"{PLATFORM_TENANT_ID}.ten_partner_1", tenant_id="ten_partner_1"
    )
    assert cycle_res.is_err
    assert cycle_res.unwrap_err().code == IdentityErrorCode.HIERARCHY_CYCLE_DETECTED

    assert detect_hierarchy_cycle(
        target_path="ten_root.ten_a",
        candidate_parent_path="ten_root.ten_a.ten_b",
    )
    assert not detect_hierarchy_cycle(
        target_path="ten_root.ten_a",
        candidate_parent_path="ten_root.ten_c",
    )


async def test_multi_tier_inheritance_block_isolation_explicit_deny_and_app_gate() -> None:
    now = datetime.now(UTC)
    directory = _FakeDirectory()
    directory.tenants[PLATFORM_TENANT_ID] = TenantNodeDTO(
        id=PLATFORM_TENANT_ID,
        parent_tenant_id=None,
        hierarchy_path=PLATFORM_TENANT_ID,
        tier_type=TenantTierType.PLATFORM,
        isolation_mode=TenantIsolationMode.POOLED_REALM,
        status="active",
        block_parent_inheritance=False,
        tokens_valid_after=_EPOCH_ZERO,
    )
    directory.tenants["ten_partner"] = TenantNodeDTO(
        id="ten_partner",
        parent_tenant_id=PLATFORM_TENANT_ID,
        hierarchy_path=f"{PLATFORM_TENANT_ID}.ten_partner",
        tier_type=TenantTierType.PARTNER,
        isolation_mode=TenantIsolationMode.POOLED_REALM,
        status="active",
        block_parent_inheritance=False,
        tokens_valid_after=_EPOCH_ZERO,
    )
    directory.tenants["ten_org_open"] = TenantNodeDTO(
        id="ten_org_open",
        parent_tenant_id="ten_partner",
        hierarchy_path=f"{PLATFORM_TENANT_ID}.ten_partner.ten_org_open",
        tier_type=TenantTierType.ORGANIZATION,
        isolation_mode=TenantIsolationMode.POOLED_REALM,
        status="active",
        block_parent_inheritance=False,
        tokens_valid_after=_EPOCH_ZERO,
    )
    directory.tenants["ten_org_isolated"] = TenantNodeDTO(
        id="ten_org_isolated",
        parent_tenant_id="ten_partner",
        hierarchy_path=f"{PLATFORM_TENANT_ID}.ten_partner.ten_org_isolated",
        tier_type=TenantTierType.ORGANIZATION,
        isolation_mode=TenantIsolationMode.DEDICATED_IDP_ORG,
        status="active",
        block_parent_inheritance=True,
        tokens_valid_after=_EPOCH_ZERO,
    )
    directory.roles["rol_partner_ops"] = RoleDefinitionDTO(
        id="rol_partner_ops",
        tenant_id="ten_partner",
        name="PartnerOps",
        capabilities=frozenset({Capability.IP_FLOWS_READ.value, Capability.IP_FLOWS_WRITE.value}),
        deny_capabilities=frozenset({Capability.IP_FLOWS_WRITE.value}),
    )
    directory.principals["iam_usr_alice"] = PrincipalSnapshotDTO(
        user_id="iam_usr_alice",
        status=UserStatus.ACTIVE,
        tokens_valid_after=_EPOCH_ZERO,
        memberships=(
            MembershipDTO(
                user_id="iam_usr_alice",
                tenant_id="ten_partner",
                scope=MembershipScope.SUBTREE,
                status=MembershipStatus.ACTIVE,
            ),
        ),
        role_assignments=(
            UserRoleAssignmentDTO(
                tenant_id="ten_partner",
                user_id="iam_usr_alice",
                role_id="rol_partner_ops",
            ),
        ),
    )

    entitlements = _FakeEntitlements(
        {"ten_org_open": frozenset({"ip"}), "ten_org_isolated": frozenset({"ip"})}
    )
    catalog = InMemoryGlobalAuthzCatalog()
    cache = L1LruPrincipalCache()
    engine = HybridLocalAuthorizationEngine(
        directory=directory,
        global_catalog=catalog,
        entitlements=entitlements,
        cache=cache,
    )
    alice = PrincipalContext(
        user_id="iam_usr_alice",
        idp_issuer="http://localhost:8080",
        idp_subject="sub-alice",
        actor_type=ActorType.HUMAN,
        token_issued_at=now,
        email="alice@partner.io",
        email_verified=True,
        idp_realm="soopa-global",
    )

    # 1. SUBTREE membership inherits read into open child org
    res_read = await engine.evaluate(
        AuthzRequest(
            principal=alice,
            app_slug="ip",
            action=Capability.IP_FLOWS_READ.value,
            tenant_id="ten_org_open",
            now=now,
        )
    )
    assert res_read.is_allowed
    assert res_read.reason_code == AuthzReasonCode.ALLOWED_BY_CAPABILITY

    # 2. Explicit DENY on role overrides ALLOW for ip:flows:write
    res_write = await engine.evaluate(
        AuthzRequest(
            principal=alice,
            app_slug="ip",
            action=Capability.IP_FLOWS_WRITE.value,
            tenant_id="ten_org_open",
            now=now,
        )
    )
    assert not res_write.is_allowed
    assert res_write.reason_code == AuthzReasonCode.DENIED_EXPLICIT_POLICY

    # 3. Unsubscribed app ("edi") immediately denied by App Subscription Gate
    res_edi = await engine.evaluate(
        AuthzRequest(
            principal=alice,
            app_slug="edi",
            action="edi:partners:read",
            tenant_id="ten_org_open",
            now=now,
        )
    )
    assert not res_edi.is_allowed
    assert res_edi.reason_code == AuthzReasonCode.DENIED_APP_NOT_SUBSCRIBED

    # 4. block_parent_inheritance=True blocks partner subtree from entering isolated subsidiary
    res_iso = await engine.evaluate(
        AuthzRequest(
            principal=alice,
            app_slug="ip",
            action=Capability.IP_FLOWS_READ.value,
            tenant_id="ten_org_isolated",
            now=now,
        )
    )
    assert not res_iso.is_allowed
    assert res_iso.reason_code == AuthzReasonCode.DENIED_NOT_TENANT_MEMBER

    # 5. Live subscription update + config-sync tombstone immediately unlocks "edi"
    entitlements.mapping["ten_org_open"] = frozenset({"ip", "edi"})
    sink = IdentityInvalidationSink(global_catalog=catalog, principal_cache=cache)
    await sink.apply_delta(
        ConfigDeltaEvent(
            event_id="evt_sub_1",
            app_id=IDENTITY_CONFIG_APP_ID,
            tenant_id="ten_org_open",
            entity_type=IdentityConfigEntityType.SUBSCRIPTION_UPDATED.value,
            entity_id="ten_org_open",
            action=ConfigChangeAction.UPSERT,
            version=1,
            txid=10,
            checksum="chk1",
            payload={},
        )
    )
    res_edi_after = await engine.evaluate(
        AuthzRequest(
            principal=alice,
            app_slug="edi",
            action=Capability.IP_FLOWS_READ.value,
            tenant_id="ten_org_open",
            now=now,
        )
    )
    assert res_edi_after.is_allowed


async def test_revocation_sso_enforcement_m2m_pinning_mfa_ownership_and_rebac() -> None:
    now = datetime.now(UTC)
    directory = _FakeDirectory()
    directory.tenants["ten_acme"] = TenantNodeDTO(
        id="ten_acme",
        parent_tenant_id=None,
        hierarchy_path="ten_acme",
        tier_type=TenantTierType.ORGANIZATION,
        isolation_mode=TenantIsolationMode.DEDICATED_IDP_ORG,
        status="active",
        block_parent_inheritance=False,
        tokens_valid_after=_EPOCH_ZERO,
        idp_realm_name="org_acme",
    )
    directory.principals["iam_usr_bob"] = PrincipalSnapshotDTO(
        user_id="iam_usr_bob",
        status=UserStatus.ACTIVE,
        tokens_valid_after=now - timedelta(minutes=2),
        memberships=(
            MembershipDTO(
                user_id="iam_usr_bob",
                tenant_id="ten_acme",
                scope=MembershipScope.DIRECT,
                status=MembershipStatus.ACTIVE,
            ),
        ),
        role_assignments=(),
    )
    catalog = InMemoryGlobalAuthzCatalog(
        capabilities=(
            CapabilityDescriptor(
                code=Capability.API_KEYS_WRITE.value,
                domain="identity",
                resource="api_keys",
                action="write",
                display_name="Manage API Keys",
                description="Sensitive",
                is_sensitive=True,
                requires_mfa=True,
                machine_allowed=False,
            ),
        ),
        email_domain_routes=(
            EmailDomainRouteDTO(
                domain="acme.com",
                tenant_id="ten_acme",
                idp_issuer="http://localhost:8080",
                idp_realm_name="org_acme",
                sso_enforced=True,
                verified_at=now,
            ),
        ),
        policy_rules=(
            PolicyRuleDTO(
                id="pol_deny_restricted",
                tenant_id="ten_acme",
                engine_type=PolicyEngineType.ABAC,
                effect=AuthzEffect.DENY,
                subject_expr="*",
                resource_type="order",
                action_pattern="orders:*",
                condition_json={"require_mfa": False},
                priority=10,
            ),
        ),
    )
    grants = _FakeResourceGrants()
    await grants.save_grant(
        ResourceGrantDTO(
            id="iam_grt_1",
            tenant_id="ten_acme",
            resource_type="stitch",
            resource_id="stch_42",
            relation="editor",
            subject_type=ResourceSubjectType.USER,
            subject_id="iam_usr_bob",
            effect=AuthzEffect.ALLOW,
        )
    )
    engine = HybridLocalAuthorizationEngine(
        directory=directory,
        global_catalog=catalog,
        entitlements=_FakeEntitlements({"ten_acme": frozenset({"ip", "consumer"})}),
        cache=L1LruPrincipalCache(),
        resource_grants=grants,
    )

    # 1. SSO bypass blocked when logging in via soopa-global instead of org_acme
    bob_wrong_realm = PrincipalContext(
        user_id="iam_usr_bob",
        idp_issuer="http://localhost:8080",
        idp_subject="sub-bob",
        actor_type=ActorType.HUMAN,
        token_issued_at=now,
        email="bob@acme.com",
        email_verified=True,
        idp_realm="soopa-global",
        mfa_verified=True,
    )
    sso_res = await engine.evaluate(
        AuthzRequest(
            principal=bob_wrong_realm,
            app_slug="ip",
            action="ip:flows:read",
            tenant_id="ten_acme",
            now=now,
        )
    )
    assert sso_res.reason_code == AuthzReasonCode.DENIED_SSO_REQUIRED
    assert AuthzObligation.REDIRECT_ENTERPRISE_SSO in sso_res.obligations

    # 2. Token issued BEFORE user.tokens_valid_after is immediately revoked
    bob_stale_token = PrincipalContext(
        user_id="iam_usr_bob",
        idp_issuer="http://localhost:8080",
        idp_subject="sub-bob",
        actor_type=ActorType.HUMAN,
        token_issued_at=now - timedelta(minutes=5),
        email="bob@acme.com",
        email_verified=True,
        idp_realm="org_acme",
        mfa_verified=True,
    )
    rev_res = await engine.evaluate(
        AuthzRequest(
            principal=bob_stale_token,
            app_slug="ip",
            action="ip:flows:read",
            tenant_id="ten_acme",
            now=now,
        )
    )
    assert rev_res.reason_code == AuthzReasonCode.DENIED_TOKEN_REVOKED

    # 3. Step-Up MFA required for api_keys:write when mfa_verified=False
    bob_no_mfa = PrincipalContext(
        user_id="iam_usr_bob",
        idp_issuer="http://localhost:8080",
        idp_subject="sub-bob",
        actor_type=ActorType.HUMAN,
        token_issued_at=now,
        email="bob@acme.com",
        email_verified=True,
        idp_realm="org_acme",
        mfa_verified=False,
    )
    mfa_res = await engine.evaluate(
        AuthzRequest(
            principal=bob_no_mfa,
            app_slug="ucp",
            action=Capability.API_KEYS_WRITE.value,
            tenant_id="ten_acme",
            now=now,
        )
    )
    assert mfa_res.reason_code == AuthzReasonCode.DENIED_STEP_UP_MFA_REQUIRED
    assert AuthzObligation.REQUIRE_MFA_STEP_UP in mfa_res.obligations

    # 4. Pure O(1) B2C / Personal ownership grants access without any role or ReBAC row
    bob_mfa = PrincipalContext(
        user_id="iam_usr_bob",
        idp_issuer="http://localhost:8080",
        idp_subject="sub-bob",
        actor_type=ActorType.HUMAN,
        token_issued_at=now,
        email="bob@acme.com",
        email_verified=True,
        idp_realm="org_acme",
        mfa_verified=True,
    )
    own_res = await engine.evaluate(
        AuthzRequest(
            principal=bob_mfa,
            app_slug="consumer",
            action="orders:write",
            tenant_id="ten_acme",
            resource=ResourceContext(
                resource_type="order",
                resource_id="ord_1",
                tenant_id="ten_acme",
                owner_user_id="iam_usr_bob",
            ),
            now=now,
        )
    )
    assert own_res.is_allowed
    assert own_res.reason_code == AuthzReasonCode.ALLOWED_BY_ABAC_OWNERSHIP

    # 5. ReBAC Resource Grant allows write on shared stitch stch_42
    rebac_res = await engine.evaluate(
        AuthzRequest(
            principal=bob_mfa,
            app_slug="ip",
            action="ip:flows:write",
            tenant_id="ten_acme",
            resource=ResourceContext(
                resource_type="stitch", resource_id="stch_42", tenant_id="ten_acme"
            ),
            now=now,
        )
    )
    assert rebac_res.is_allowed
    assert rebac_res.reason_code == AuthzReasonCode.ALLOWED_BY_RESOURCE_GRANT

    # 6. M2M tenant pinning + machine_allowed=False + scope intersection
    m2m_ok = PrincipalContext(
        user_id="iam_tok_1",
        idp_issuer="soopa:api_key",
        idp_subject="cli_1",
        actor_type=ActorType.MACHINE,
        token_issued_at=now,
        bound_tenant_id="ten_acme",
        token_scopes=frozenset({"ip:flows:read"}),
    )
    assert (
        await engine.evaluate(
            AuthzRequest(
                principal=m2m_ok,
                app_slug="ip",
                action="ip:flows:read",
                tenant_id="ten_acme",
                now=now,
            )
        )
    ).is_allowed
    assert (
        await engine.evaluate(
            AuthzRequest(
                principal=m2m_ok,
                app_slug="ucp",
                action=Capability.API_KEYS_WRITE.value,
                tenant_id="ten_acme",
                now=now,
            )
        )
    ).reason_code == AuthzReasonCode.DENIED_MACHINE_ACTION_FORBIDDEN
    m2m_wrong_tenant = PrincipalContext(
        user_id="iam_tok_1",
        idp_issuer="soopa:api_key",
        idp_subject="cli_1",
        actor_type=ActorType.MACHINE,
        token_issued_at=now,
        bound_tenant_id="ten_other",
        token_scopes=frozenset({"*"}),
    )
    assert (
        await engine.evaluate(
            AuthzRequest(
                principal=m2m_wrong_tenant,
                app_slug="ip",
                action="ip:flows:read",
                tenant_id="ten_acme",
                now=now,
            )
        )
    ).reason_code == AuthzReasonCode.DENIED_TENANT_SCOPE_MISMATCH

    # 7. Break-glass support impersonation blocks destructive IAM mutations
    imp = PrincipalContext(
        user_id="iam_usr_bob",
        idp_issuer="http://localhost:8080",
        idp_subject="sub-bob",
        actor_type=ActorType.DELEGATED_SUPPORT,
        token_issued_at=now,
        mfa_verified=True,
        impersonator_user_id="iam_usr_sre",
        impersonation_ticket_id="SUP-991",
        impersonation_expires_at=now + timedelta(minutes=30),
    )
    assert (
        await engine.evaluate(
            AuthzRequest(
                principal=imp,
                app_slug="ucp",
                action=Capability.ROLES_WRITE.value,
                tenant_id="ten_acme",
                now=now,
            )
        )
    ).reason_code == AuthzReasonCode.DENIED_IMPERSONATION_POLICY


async def test_jit_provision_zero_trust_anti_pre_hijacking() -> None:
    now = datetime.now(UTC)
    ext_repo = _FakeExternalIdentities()
    user_repo = _FakeUserRepo()
    catalog = InMemoryGlobalAuthzCatalog(
        trusted_issuers=(
            TrustedIssuerDTO(
                issuer="https://auth.soopa.io", jwks_uri="https://auth.soopa.io/.well-known/jwks"
            ),
            TrustedIssuerDTO(
                issuer="https://login.microsoftonline.com/acme/v2.0",
                jwks_uri="https://login.microsoftonline.com/acme/keys",
            ),
        ),
        email_domain_routes=(
            EmailDomainRouteDTO(
                domain="acme.com",
                tenant_id="ten_acme",
                idp_issuer="https://login.microsoftonline.com/acme/v2.0",
                idp_realm_name="entra-acme",
                sso_enforced=True,
                verified_at=now,
            ),
        ),
    )
    uc = JitProvisionUserUseCase(
        external_identity_repo=ext_repo,
        user_repo=user_repo,
        global_catalog=catalog,
    )

    # 1. Untrusted issuer rejected
    bad_iss = await uc.execute(
        JitProvisionUserCommand(
            idp_issuer="https://evil.example.com",
            idp_subject="sub-1",
            email="alice@acme.com",
            email_verified=True,
            display_name="Alice",
        )
    )
    assert bad_iss.is_err
    assert bad_iss.unwrap_err().code == IdentityErrorCode.UNTRUSTED_ISSUER

    # 2. First-time user created atomically + linked
    first = await uc.execute(
        JitProvisionUserCommand(
            idp_issuer="https://auth.soopa.io",
            idp_subject="casdoor-sub-1",
            email="alice@acme.com",
            email_verified=True,
            display_name="Alice",
            idp_realm_name="soopa-global",
        )
    )
    assert first.is_ok
    assert first.unwrap().created is True

    # 3. Unverified or non-SSO duplicate email from another subject MUST NOT auto-merge
    hijack = await uc.execute(
        JitProvisionUserCommand(
            idp_issuer="https://auth.soopa.io",
            idp_subject="casdoor-sub-attacker",
            email="alice@acme.com",
            email_verified=False,
            display_name="Attacker",
            idp_realm_name="soopa-global",
        )
    )
    assert hijack.is_err
    assert hijack.unwrap_err().code == IdentityErrorCode.ACCOUNT_LINK_CONFIRMATION_REQUIRED

    # 4. Verified Enterprise SSO route for acme.com cleanly links Entra subject to existing iam_usr_...
    sso_link = await uc.execute(
        JitProvisionUserCommand(
            idp_issuer="https://login.microsoftonline.com/acme/v2.0",
            idp_subject="entra-oid-alice",
            email="alice@acme.com",
            email_verified=True,
            display_name="Alice",
            idp_realm_name="entra-acme",
        )
    )
    assert sso_link.is_ok
    assert sso_link.unwrap().created is False
    assert sso_link.unwrap().user_id == first.unwrap().user_id


async def test_generic_oidc_jwks_verifier_multi_issuer_rs256_and_minimal_claims() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk_dict = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk_dict["kid"] = "k1"
    jwk_dict["use"] = "sig"
    jwk_dict["alg"] = "RS256"

    jwks_calls = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal jwks_calls
        if str(request.url) == "http://127.0.0.1:8080/.well-known/jwks":
            jwks_calls += 1
            return httpx.Response(200, json={"keys": [jwk_dict]})
        return httpx.Response(404)

    client = HttpClient(
        httpx.AsyncClient(transport=httpx.MockTransport(_handler)),
        allow_private_ips=True,
    )
    verifier = OidcJwksTokenVerifierAdapter(
        options=OidcTokenVerifierOptions(
            default_issuer="http://127.0.0.1:8080",
            default_jwks_uri="http://127.0.0.1:8080/.well-known/jwks",
            default_audiences=("soopa-dashboard",),
            allow_private_ips=True,
        ),
        http_client=client,
    )
    now_ts = int(datetime.now(UTC).timestamp())
    token = jwt.encode(
        {
            "iss": "http://127.0.0.1:8080",
            "sub": "uuid-user-1",
            "aud": "soopa-dashboard",
            "exp": now_ts + 600,
            "iat": now_ts,
            "jti": "jti_1",
            "owner": "soopa-global",
            "email": "alice@example.com",
            "email_verified": True,
            "acr": "aal2",
            "amr": ["pwd", "webauthn"],
            "act": {"sub": "uuid-sre-1", "ticket_id": "SUP-101"},
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "k1"},
    )
    assert len(token) < 900  # Compact RS256 signed JWT (<600B payload)

    res1 = await verifier.verify_result(token)
    res2 = await verifier.verify_result(token)
    assert res1.is_ok and res2.is_ok
    assert jwks_calls == 1  # Cached JWKS — zero extra HTTP calls!
    claims = res1.unwrap()
    assert claims.sub == "uuid-user-1"
    assert claims.idp_realm == "soopa-global"
    assert claims.email == "alice@example.com"
    assert claims.email_verified is True
    assert claims.amr == ("pwd", "webauthn")
    assert claims.impersonator_subject == "uuid-sre-1"
    assert claims.impersonation_ticket_id == "SUP-101"
