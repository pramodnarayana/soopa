"""Zero-mock unit tests verifying the Step 3 Identity / AuthZ Hot-Path Cutover."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated

import pytest
import structlog.testing
from fastapi import Depends, FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient
from identity.adapters.outbound.cache.in_memory_global_authz_catalog import (
    InMemoryGlobalAuthzCatalog,
)
from identity.adapters.outbound.cache.l1_lru_principal_cache import L1LruPrincipalCache
from identity.application.authorize_use_case import HybridLocalAuthorizationEngine
from identity.domain.authorization import Capability, CapabilityDescriptor
from identity.domain.constants import (
    ActorType,
    AuthzReasonCode,
    MembershipScope,
    TenantIsolationMode,
    TenantTierType,
    UserStatus,
)
from identity.domain.dtos import (
    MembershipDTO,
    PrincipalSnapshotDTO,
    RoleDefinitionDTO,
    TenantNodeDTO,
    UserRoleAssignmentDTO,
)
from identity.domain.identity_context import PLATFORM_TENANT_ID, IdentityContext
from identity.ports.outbound.authorization_engine_port import AuthorizationEnginePort
from identity.ports.outbound.tenant_entitlement_port import TenantEntitlementPort
from identity.ports.outbound.tenant_hierarchy_port import AuthzDirectoryPort
from sqlalchemy.ext.asyncio import AsyncSession
from ucp.ports.outbound.tenant_repository_port import TenantRepositoryPort

from unified_api.adapters.inbound.http.guards.notification_auth_guard import (
    assert_tenant_authorized,
    assert_user_matches_identity,
)
from unified_api.adapters.inbound.http.guards.platform_auth_guard import require_platform_admin
from unified_api.adapters.inbound.http.guards.require_capability_guard import RequireCapability
from unified_api.adapters.inbound.http.guards.tenant_auth_guard import require_tenant_member
from unified_api.adapters.inbound.http.middleware.authentication import (
    AuthenticationMiddleware,
    _to_principal_context,
)

_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
_OLD_EPOCH = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)


@dataclass
class _InMemoryAuthzDirectory(AuthzDirectoryPort):
    principals: dict[str, PrincipalSnapshotDTO] = field(default_factory=dict)
    tenants: dict[str, TenantNodeDTO] = field(default_factory=dict)
    roles: dict[str, RoleDefinitionDTO] = field(default_factory=dict)
    principal_loads: int = 0
    tenant_chain_loads: int = 0
    role_loads: int = 0

    async def get_principal_snapshot(self, *, user_id: str) -> PrincipalSnapshotDTO | None:
        self.principal_loads += 1
        return self.principals.get(user_id)

    async def get_tenant_ancestor_chain(self, *, tenant_id: str) -> tuple[TenantNodeDTO, ...]:
        self.tenant_chain_loads += 1
        leaf = self.tenants.get(tenant_id)
        if leaf is None:
            return ()
        ids = [seg for seg in leaf.hierarchy_path.split(".") if seg]
        return tuple(self.tenants[tid] for tid in ids if tid in self.tenants)

    async def get_roles_by_ids(self, *, role_ids: Sequence[str]) -> dict[str, RoleDefinitionDTO]:
        self.role_loads += 1
        return {rid: self.roles[rid] for rid in role_ids if rid in self.roles}


@dataclass
class _InMemoryEntitlements(TenantEntitlementPort):
    enabled_by_tenant: dict[str, frozenset[str]] = field(default_factory=dict)
    loads: int = 0

    async def get_enabled_app_slugs(self, *, tenant_id: str) -> frozenset[str]:
        self.loads += 1
        return self.enabled_by_tenant.get(tenant_id, frozenset())


class _NoOpDbProvider:
    @contextlib.asynccontextmanager
    async def session(self) -> AsyncIterator[None]:
        yield None


@dataclass
class _FakeAuthzRuntime:
    directory: _InMemoryAuthzDirectory
    entitlements: _InMemoryEntitlements
    global_catalog: InMemoryGlobalAuthzCatalog = field(default_factory=InMemoryGlobalAuthzCatalog)
    principal_cache: L1LruPrincipalCache = field(
        default_factory=lambda: L1LruPrincipalCache(max_principals=100, ttl_seconds=60.0)
    )

    def _build_local_pdp(self) -> HybridLocalAuthorizationEngine:
        return HybridLocalAuthorizationEngine(
            directory=self.directory,
            global_catalog=self.global_catalog,
            entitlements=self.entitlements,
            cache=self.principal_cache,
        )

    def build_engine(self, session: object) -> AuthorizationEnginePort:
        _ = session
        return self._build_local_pdp()

    async def has_hierarchical_tenant_access(
        self,
        *,
        session: object,
        user_id: str,
        target_tenant_id: str,
    ) -> bool:
        _ = session
        return await self._build_local_pdp().has_active_tenant_access(
            user_id=user_id,
            target_tenant_id=target_tenant_id,
        )


class _StaticIdentityStrategy:
    def __init__(self, identity: IdentityContext) -> None:
        self._identity = identity

    def can_handle(self, token: str) -> bool:
        return bool(token)

    async def authenticate(self, token: str) -> IdentityContext:
        _ = token
        return self._identity


def _tenant_node(
    tenant_id: str,
    *,
    parent_tenant_id: str | None = None,
    hierarchy_path: str | None = None,
    status: str = "active",
    block_parent_inheritance: bool = False,
) -> TenantNodeDTO:
    return TenantNodeDTO(
        id=tenant_id,
        parent_tenant_id=parent_tenant_id,
        hierarchy_path=hierarchy_path or tenant_id,
        tier_type=TenantTierType.ORGANIZATION,
        isolation_mode=TenantIsolationMode.POOLED_REALM,
        status=status,
        block_parent_inheritance=block_parent_inheritance,
        tokens_valid_after=_OLD_EPOCH,
    )


def _build_runtime_app(
    *,
    identity: IdentityContext,
    runtime: _FakeAuthzRuntime,
) -> FastAPI:
    app = FastAPI()
    app.state.identity_authz = runtime
    app.state.db_provider = _NoOpDbProvider()
    app.add_middleware(
        AuthenticationMiddleware,
        strategies=[_StaticIdentityStrategy(identity)],
        public_paths=frozenset(),
    )

    @app.post(
        "/api/v1/tenants/{tenant_id}/users",
        dependencies=[Depends(RequireCapability(Capability.USERS_WRITE))],
    )
    async def create_user(tenant_id: str) -> dict[str, str]:
        return {"ok": tenant_id}

    @app.get(
        "/api/v1/tenants/{tenant_id}/ip-flows",
        dependencies=[Depends(RequireCapability(Capability.IP_FLOWS_READ, app_slug="ip"))],
    )
    async def list_ip_flows(tenant_id: str) -> dict[str, str]:
        return {"flows": tenant_id}

    @app.post(
        "/api/v1/tenants/{tenant_id}/ip-flows",
        dependencies=[Depends(RequireCapability(Capability.IP_FLOWS_WRITE, app_slug="ip"))],
    )
    async def write_ip_flows(tenant_id: str) -> dict[str, str]:
        return {"flows_written": tenant_id}

    @app.get(
        "/api/v1/tenants/{tenant_id}",
        dependencies=[Depends(RequireCapability(Capability.TENANT_SETTINGS_READ))],
    )
    async def get_tenant(tenant_id: str) -> dict[str, str]:
        if tenant_id not in runtime.directory.tenants:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return {"id": tenant_id}

    @app.delete(
        "/api/v1/tenants/{tenant_id}",
        dependencies=[Depends(RequireCapability(Capability.PLATFORM_ADMIN))],
    )
    async def delete_tenant(tenant_id: str) -> dict[str, str]:
        return {"deleted": tenant_id}

    @app.get("/api/v1/platform-check")
    async def platform_check(
        _admin: Annotated[IdentityContext, Depends(require_platform_admin)],
    ) -> dict[str, bool]:
        return {"platform": True}

    return app


@pytest.mark.asyncio
async def test_require_capability_uses_l1_cache_with_zero_db_hits_on_repeat_request() -> None:
    directory = _InMemoryAuthzDirectory(
        principals={
            "iam_usr_alice": PrincipalSnapshotDTO(
                user_id="iam_usr_alice",
                status=UserStatus.ACTIVE,
                tokens_valid_after=_OLD_EPOCH,
                memberships=(MembershipDTO(user_id="iam_usr_alice", tenant_id="ten_a"),),
                role_assignments=(
                    UserRoleAssignmentDTO(
                        tenant_id="ten_a",
                        user_id="iam_usr_alice",
                        role_id="rol_admin",
                    ),
                ),
            )
        },
        tenants={"ten_a": _tenant_node("ten_a")},
        roles={
            "rol_admin": RoleDefinitionDTO(
                id="rol_admin",
                tenant_id="ten_a",
                name="TenantAdmin",
                capabilities=frozenset({Capability.USERS_WRITE.value}),
            )
        },
    )
    runtime = _FakeAuthzRuntime(directory=directory, entitlements=_InMemoryEntitlements())
    identity = IdentityContext(
        subject="iam_usr_alice",
        tenant_id="ten_a",
        authorized_tenants={"ten_a"},
        claims={"iss": "https://idp.example", "sub": "alice", "iat": int(_NOW.timestamp())},
    )
    app = _build_runtime_app(identity=identity, runtime=runtime)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.post(
            "/api/v1/tenants/ten_a/users", headers={"Authorization": "Bearer jwt"}
        )
        r2 = await client.post(
            "/api/v1/tenants/ten_a/users", headers={"Authorization": "Bearer jwt"}
        )

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert directory.principal_loads == 1
    assert directory.tenant_chain_loads == 1
    assert directory.role_loads == 1


@pytest.mark.asyncio
async def test_require_capability_prevents_cross_tenant_privilege_escalation() -> None:
    """Alice is TenantAdmin in ten_a (default) and Viewer in ten_b; writing users in ten_b MUST fail."""
    directory = _InMemoryAuthzDirectory(
        principals={
            "iam_usr_alice": PrincipalSnapshotDTO(
                user_id="iam_usr_alice",
                status=UserStatus.ACTIVE,
                tokens_valid_after=_OLD_EPOCH,
                memberships=(
                    MembershipDTO(user_id="iam_usr_alice", tenant_id="ten_a"),
                    MembershipDTO(user_id="iam_usr_alice", tenant_id="ten_b"),
                ),
                role_assignments=(
                    UserRoleAssignmentDTO(
                        tenant_id="ten_a", user_id="iam_usr_alice", role_id="rol_admin"
                    ),
                    UserRoleAssignmentDTO(
                        tenant_id="ten_b", user_id="iam_usr_alice", role_id="rol_viewer"
                    ),
                ),
            )
        },
        tenants={"ten_a": _tenant_node("ten_a"), "ten_b": _tenant_node("ten_b")},
        roles={
            "rol_admin": RoleDefinitionDTO(
                id="rol_admin",
                tenant_id="ten_a",
                name="TenantAdmin",
                capabilities=frozenset({Capability.USERS_WRITE.value}),
            ),
            "rol_viewer": RoleDefinitionDTO(
                id="rol_viewer",
                tenant_id="ten_b",
                name="Viewer",
                capabilities=frozenset({Capability.USERS_READ.value}),
            ),
        },
    )
    runtime = _FakeAuthzRuntime(directory=directory, entitlements=_InMemoryEntitlements())
    # Even if stale default-tenant capabilities contain USERS_WRITE from ten_a:
    identity = IdentityContext(
        subject="iam_usr_alice",
        tenant_id="ten_a",
        authorized_tenants={"ten_a", "ten_b"},
        capabilities={Capability.USERS_WRITE.value},
        claims={"iss": "https://idp.example", "sub": "alice", "iat": int(_NOW.timestamp())},
    )
    app = _build_runtime_app(identity=identity, runtime=runtime)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ok = await client.post(
            "/api/v1/tenants/ten_a/users", headers={"Authorization": "Bearer jwt"}
        )
        denied = await client.post(
            "/api/v1/tenants/ten_b/users", headers={"Authorization": "Bearer jwt"}
        )

    assert ok.status_code == 200
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == AuthzReasonCode.DENIED_MISSING_CAPABILITY.value


@pytest.mark.asyncio
async def test_require_capability_enforces_token_revocation_explicit_deny_and_app_entitlement() -> (
    None
):
    revoked_cutoff = _NOW + timedelta(minutes=10)
    directory = _InMemoryAuthzDirectory(
        principals={
            "iam_usr_revoked": PrincipalSnapshotDTO(
                user_id="iam_usr_revoked",
                status=UserStatus.ACTIVE,
                tokens_valid_after=revoked_cutoff,
                memberships=(MembershipDTO(user_id="iam_usr_revoked", tenant_id="ten_a"),),
                role_assignments=(
                    UserRoleAssignmentDTO(
                        tenant_id="ten_a", user_id="iam_usr_revoked", role_id="rol_admin"
                    ),
                ),
            ),
            "iam_usr_denied": PrincipalSnapshotDTO(
                user_id="iam_usr_denied",
                status=UserStatus.ACTIVE,
                tokens_valid_after=_OLD_EPOCH,
                memberships=(MembershipDTO(user_id="iam_usr_denied", tenant_id="ten_a"),),
                role_assignments=(
                    UserRoleAssignmentDTO(
                        tenant_id="ten_a", user_id="iam_usr_denied", role_id="rol_deny"
                    ),
                ),
            ),
        },
        tenants={"ten_a": _tenant_node("ten_a")},
        roles={
            "rol_admin": RoleDefinitionDTO(
                id="rol_admin",
                tenant_id="ten_a",
                name="TenantAdmin",
                capabilities=frozenset(
                    {Capability.USERS_WRITE.value, Capability.IP_FLOWS_READ.value}
                ),
            ),
            "rol_deny": RoleDefinitionDTO(
                id="rol_deny",
                tenant_id="ten_a",
                name="RestrictedAdmin",
                capabilities=frozenset(
                    {Capability.USERS_WRITE.value, Capability.IP_FLOWS_READ.value}
                ),
                deny_capabilities=frozenset({Capability.USERS_WRITE.value}),
            ),
        },
    )
    entitlements = _InMemoryEntitlements(enabled_by_tenant={"ten_a": frozenset()})
    runtime = _FakeAuthzRuntime(directory=directory, entitlements=entitlements)

    # 1. Revoked token -> 401 with WWW-Authenticate: Bearer
    revoked_identity = IdentityContext(
        subject="iam_usr_revoked",
        tenant_id="ten_a",
        authorized_tenants={"ten_a"},
        claims={"iss": "https://idp.example", "sub": "revoked", "iat": int(_NOW.timestamp())},
    )
    revoked_app = _build_runtime_app(identity=revoked_identity, runtime=runtime)
    async with AsyncClient(
        transport=ASGITransport(app=revoked_app), base_url="http://test"
    ) as client:
        r_revoked = await client.post(
            "/api/v1/tenants/ten_a/users", headers={"Authorization": "Bearer jwt"}
        )
    assert r_revoked.status_code == 401
    assert r_revoked.headers["www-authenticate"] == "Bearer"
    assert r_revoked.json()["detail"]["code"] == AuthzReasonCode.DENIED_TOKEN_REVOKED.value

    # 2. Explicit DENY wins over ALLOW + App Subscription Gate blocks unsubscribed IP app
    denied_identity = IdentityContext(
        subject="iam_usr_denied",
        tenant_id="ten_a",
        authorized_tenants={"ten_a"},
        claims={"iss": "https://idp.example", "sub": "denied", "iat": int(_NOW.timestamp())},
    )
    denied_app = _build_runtime_app(identity=denied_identity, runtime=runtime)
    async with AsyncClient(
        transport=ASGITransport(app=denied_app), base_url="http://test"
    ) as client:
        r_explicit_deny = await client.post(
            "/api/v1/tenants/ten_a/users", headers={"Authorization": "Bearer jwt"}
        )
        r_unsub = await client.get(
            "/api/v1/tenants/ten_a/ip-flows", headers={"Authorization": "Bearer jwt"}
        )
        # Subscribe tenant to "ip" and evict L1 entitlement cache -> now allowed!
        entitlements.enabled_by_tenant["ten_a"] = frozenset({"ip"})
        await runtime.principal_cache.evict_enabled_apps("ten_a")
        r_sub = await client.get(
            "/api/v1/tenants/ten_a/ip-flows", headers={"Authorization": "Bearer jwt"}
        )

    assert r_explicit_deny.status_code == 403
    assert r_explicit_deny.json()["detail"]["code"] == AuthzReasonCode.DENIED_EXPLICIT_POLICY.value
    assert r_unsub.status_code == 403
    assert r_unsub.json()["detail"]["code"] == AuthzReasonCode.DENIED_APP_NOT_SUBSCRIBED.value
    assert r_sub.status_code == 200


@pytest.mark.asyncio
async def test_hierarchical_subtree_inheritance_and_block_parent_inheritance() -> None:
    directory = _InMemoryAuthzDirectory(
        principals={
            "iam_usr_parent": PrincipalSnapshotDTO(
                user_id="iam_usr_parent",
                status=UserStatus.ACTIVE,
                tokens_valid_after=_OLD_EPOCH,
                memberships=(
                    MembershipDTO(
                        user_id="iam_usr_parent",
                        tenant_id="ten_parent",
                        scope=MembershipScope.SUBTREE,
                    ),
                ),
                role_assignments=(
                    UserRoleAssignmentDTO(
                        tenant_id="ten_parent",
                        user_id="iam_usr_parent",
                        role_id="rol_parent_admin",
                    ),
                ),
            )
        },
        tenants={
            "ten_parent": _tenant_node("ten_parent"),
            "ten_child": _tenant_node(
                "ten_child",
                parent_tenant_id="ten_parent",
                hierarchy_path="ten_parent.ten_child",
            ),
            "ten_isolated": _tenant_node(
                "ten_isolated",
                parent_tenant_id="ten_parent",
                hierarchy_path="ten_parent.ten_isolated",
                block_parent_inheritance=True,
            ),
        },
        roles={
            "rol_parent_admin": RoleDefinitionDTO(
                id="rol_parent_admin",
                tenant_id="ten_parent",
                name="ParentAdmin",
                capabilities=frozenset({Capability.USERS_WRITE.value}),
            )
        },
    )
    runtime = _FakeAuthzRuntime(directory=directory, entitlements=_InMemoryEntitlements())
    identity = IdentityContext(
        subject="iam_usr_parent",
        tenant_id="ten_parent",
        authorized_tenants={"ten_parent"},
        claims={"iss": "https://idp.example", "sub": "parent", "iat": int(_NOW.timestamp())},
    )
    app = _build_runtime_app(identity=identity, runtime=runtime)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ok_child = await client.post(
            "/api/v1/tenants/ten_child/users", headers={"Authorization": "Bearer jwt"}
        )
        blocked_child = await client.post(
            "/api/v1/tenants/ten_isolated/users", headers={"Authorization": "Bearer jwt"}
        )

    assert ok_child.status_code == 200
    assert blocked_child.status_code == 403
    assert blocked_child.json()["detail"]["code"] == AuthzReasonCode.DENIED_NOT_TENANT_MEMBER.value


@pytest.mark.asyncio
async def test_m2m_api_key_principal_context_enforces_tenant_pinning_and_scopes() -> None:
    m2m_identity = IdentityContext(
        subject="machine_cli_1",
        tenant_id="ten_a",
        authorized_tenants={"ten_a"},
        claims={"client_id": "cli_1", "is_m2m": True},
        capabilities={Capability.IP_FLOWS_READ.value},
    )
    principal = _to_principal_context(m2m_identity)
    assert principal.actor_type == ActorType.MACHINE
    assert principal.bound_tenant_id == "ten_a"
    assert principal.token_scopes == frozenset({Capability.IP_FLOWS_READ.value})

    directory = _InMemoryAuthzDirectory(
        tenants={"ten_a": _tenant_node("ten_a"), "ten_b": _tenant_node("ten_b")}
    )
    entitlements = _InMemoryEntitlements(
        enabled_by_tenant={"ten_a": frozenset({"ip"}), "ten_b": frozenset({"ip"})}
    )
    runtime = _FakeAuthzRuntime(directory=directory, entitlements=entitlements)
    runtime.global_catalog.upsert_capability(
        CapabilityDescriptor(
            code=Capability.IP_FLOWS_READ.value,
            domain="ip",
            resource="flows",
            action="read",
            display_name="Read IP Flows",
            description="Read IP flows",
            machine_allowed=True,
        )
    )
    app = _build_runtime_app(identity=m2m_identity, runtime=runtime)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_ok = await client.get(
            "/api/v1/tenants/ten_a/ip-flows", headers={"Authorization": "Bearer sp_api_key"}
        )
        r_missing_scope = await client.post(
            "/api/v1/tenants/ten_a/ip-flows", headers={"Authorization": "Bearer sp_api_key"}
        )
        r_wrong_tenant = await client.get(
            "/api/v1/tenants/ten_b/ip-flows", headers={"Authorization": "Bearer sp_api_key"}
        )

    assert r_ok.status_code == 200
    assert r_missing_scope.status_code == 403
    assert (
        r_missing_scope.json()["detail"]["code"] == AuthzReasonCode.DENIED_MISSING_CAPABILITY.value
    )
    assert r_wrong_tenant.status_code == 403
    assert (
        r_wrong_tenant.json()["detail"]["code"]
        == AuthzReasonCode.DENIED_TENANT_SCOPE_MISMATCH.value
    )


@pytest.mark.asyncio
async def test_platform_admin_can_manage_suspended_tenant_and_gets_404_on_deleted_tenant() -> None:
    directory = _InMemoryAuthzDirectory(
        principals={
            "iam_usr_padmin": PrincipalSnapshotDTO(
                user_id="iam_usr_padmin",
                status=UserStatus.ACTIVE,
                tokens_valid_after=_OLD_EPOCH,
                memberships=(
                    MembershipDTO(
                        user_id="iam_usr_padmin",
                        tenant_id=PLATFORM_TENANT_ID,
                        scope=MembershipScope.SUBTREE,
                    ),
                ),
                role_assignments=(
                    UserRoleAssignmentDTO(
                        tenant_id=PLATFORM_TENANT_ID,
                        user_id="iam_usr_padmin",
                        role_id="rol_platform",
                    ),
                ),
            )
        },
        tenants={
            PLATFORM_TENANT_ID: _tenant_node(PLATFORM_TENANT_ID),
            "ten_suspended": _tenant_node("ten_suspended", status="inactive"),
        },
        roles={
            "rol_platform": RoleDefinitionDTO(
                id="rol_platform",
                tenant_id=PLATFORM_TENANT_ID,
                name="PlatformAdmin",
                capabilities=frozenset({Capability.PLATFORM_ADMIN.value}),
            )
        },
    )
    runtime = _FakeAuthzRuntime(directory=directory, entitlements=_InMemoryEntitlements())
    identity = IdentityContext(
        subject="iam_usr_padmin",
        tenant_id=PLATFORM_TENANT_ID,
        authorized_tenants={PLATFORM_TENANT_ID},
        capabilities={Capability.PLATFORM_ADMIN.value},
        claims={"iss": "https://idp.example", "sub": "padmin", "iat": int(_NOW.timestamp())},
    )
    app = _build_runtime_app(identity=identity, runtime=runtime)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_del_suspended = await client.delete(
            "/api/v1/tenants/ten_suspended", headers={"Authorization": "Bearer jwt"}
        )
        r_deleted_404 = await client.get(
            "/api/v1/tenants/ten_does_not_exist", headers={"Authorization": "Bearer jwt"}
        )
        r_platform_guard = await client.get(
            "/api/v1/platform-check", headers={"Authorization": "Bearer jwt"}
        )

    assert r_del_suspended.status_code == 200
    assert r_deleted_404.status_code == 404
    assert r_platform_guard.status_code == 200


@pytest.mark.asyncio
async def test_require_tenant_member_never_mutates_identity_capabilities() -> None:
    original_caps = {Capability.PLATFORM_ADMIN.value, Capability.USERS_READ.value}
    identity = IdentityContext(
        subject="iam_usr_admin",
        tenant_id=PLATFORM_TENANT_ID,
        authorized_tenants={PLATFORM_TENANT_ID},
        capabilities=set(original_caps),
        claims={},
    )
    request = Request(scope={"type": "http", "path": "/api/v1/tenants/ten_customer/users"})
    request.state.identity = identity

    def _unused_repo_factory(_session: AsyncSession) -> TenantRepositoryPort:
        raise AssertionError("Canonical ten_ ID must NOT query tenant_repo.find_by_idp_realm")

    returned = await require_tenant_member(
        request=request,
        session=AsyncSession(),
        tenant_repo_factory=_unused_repo_factory,
        tenant_id="ten_customer",
    )

    assert returned is identity
    assert identity.capabilities == original_caps
    assert request.state.ucp_tenant_id == "ten_customer"


@pytest.mark.asyncio
async def test_platform_and_notification_guards_log_errors_never_warnings() -> None:
    non_admin = IdentityContext(
        subject="iam_usr_bob",
        tenant_id="ten_a",
        authorized_tenants={"ten_a"},
        claims={},
    )
    request = Request(scope={"type": "http", "path": "/api/v1/admin/secret", "headers": []})
    request.state.identity = non_admin

    with structlog.testing.capture_logs() as cap_logs:
        with pytest.raises(HTTPException) as exc_platform:
            await require_platform_admin(request)
        with pytest.raises(HTTPException) as exc_tenant_idor:
            assert_tenant_authorized(request, "ten_other")
        with pytest.raises(HTTPException) as exc_user_idor:
            assert_user_matches_identity(request, "iam_usr_other")

    assert exc_platform.value.status_code == 403
    assert exc_tenant_idor.value.status_code == 403
    assert exc_user_idor.value.status_code == 403
    assert len(cap_logs) == 3
    assert all(entry["log_level"] == "error" for entry in cap_logs)
    assert {entry["event"] for entry in cap_logs} == {
        "authz.denied.platform_admin_required",
        "authz.denied.tenant_idor",
        "authz.denied.user_idor",
    }


@pytest.mark.asyncio
async def test_child_tenant_ltree_chain_hits_l1_cache_and_rejects_suspended_hierarchy() -> None:
    directory = _InMemoryAuthzDirectory(
        principals={
            "iam_usr_parent": PrincipalSnapshotDTO(
                user_id="iam_usr_parent",
                status=UserStatus.ACTIVE,
                tokens_valid_after=_OLD_EPOCH,
                memberships=(
                    MembershipDTO(
                        user_id="iam_usr_parent",
                        tenant_id="ten_root",
                        scope=MembershipScope.SUBTREE,
                    ),
                ),
                role_assignments=(
                    UserRoleAssignmentDTO(
                        tenant_id="ten_root",
                        user_id="iam_usr_parent",
                        role_id="rol_admin",
                    ),
                ),
            )
        },
        tenants={
            "ten_root": _tenant_node("ten_root"),
            "ten_mid": _tenant_node(
                "ten_mid",
                parent_tenant_id="ten_root",
                hierarchy_path="ten_root.ten_mid",
            ),
            "ten_leaf": _tenant_node(
                "ten_leaf",
                parent_tenant_id="ten_mid",
                hierarchy_path="ten_root.ten_mid.ten_leaf",
            ),
            "ten_suspended_leaf": _tenant_node(
                "ten_suspended_leaf",
                parent_tenant_id="ten_mid",
                hierarchy_path="ten_root.ten_mid.ten_suspended_leaf",
                status="inactive",
            ),
        },
        roles={
            "rol_admin": RoleDefinitionDTO(
                id="rol_admin",
                tenant_id="ten_root",
                name="SubtreeAdmin",
                capabilities=frozenset({Capability.USERS_WRITE.value}),
            )
        },
    )
    runtime = _FakeAuthzRuntime(directory=directory, entitlements=_InMemoryEntitlements())
    identity = IdentityContext(
        subject="iam_usr_parent",
        tenant_id="ten_root",
        authorized_tenants={"ten_root"},
        claims={"iss": "https://idp.example", "sub": "parent", "iat": int(_NOW.timestamp())},
    )
    app = _build_runtime_app(identity=identity, runtime=runtime)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.post(
            "/api/v1/tenants/ten_leaf/users", headers={"Authorization": "Bearer jwt"}
        )
        r2 = await client.post(
            "/api/v1/tenants/ten_leaf/users", headers={"Authorization": "Bearer jwt"}
        )

    assert r1.status_code == 200
    assert r2.status_code == 200
    # 3-level ltree child chain resolved from L1 cache on 2nd request (0 extra DB queries!)
    assert directory.tenant_chain_loads == 1
    assert directory.principal_loads == 1

    # Suspended leaf must be rejected by has_hierarchical_tenant_access
    assert (
        await runtime.has_hierarchical_tenant_access(
            session=None,
            user_id="iam_usr_parent",
            target_tenant_id="ten_leaf",
        )
        is True
    )
    assert (
        await runtime.has_hierarchical_tenant_access(
            session=None,
            user_id="iam_usr_parent",
            target_tenant_id="ten_suspended_leaf",
        )
        is False
    )


@pytest.mark.asyncio
async def test_require_capability_fails_closed_when_pdp_runtime_is_incomplete() -> None:
    runtime = _FakeAuthzRuntime(
        directory=_InMemoryAuthzDirectory(),
        entitlements=_InMemoryEntitlements(),
    )
    app = FastAPI()
    app.state.identity_authz = runtime
    # Intentionally omit db_provider to simulate incomplete runtime wiring
    app.state.db_provider = None

    identity = IdentityContext(
        subject="iam_usr_admin",
        tenant_id="ten_a",
        authorized_tenants={"ten_a"},
        capabilities={Capability.USERS_WRITE.value},
        claims={},
    )
    request = Request(
        scope={
            "type": "http",
            "path": "/api/v1/tenants/ten_a/users",
            "headers": [],
            "app": app,
        }
    )
    request.state.identity = identity
    request.state.principal = _to_principal_context(identity)

    guard = RequireCapability(Capability.USERS_WRITE)
    with structlog.testing.capture_logs() as cap_logs, pytest.raises(HTTPException) as exc_info:
        await guard(request)

    assert exc_info.value.status_code == 503
    assert any(
        entry["event"] == "authz.pdp.runtime_incomplete" and entry["log_level"] == "error"
        for entry in cap_logs
    )
