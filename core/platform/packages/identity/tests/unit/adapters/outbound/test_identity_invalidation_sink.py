"""Behavioral unit tests for IdentityInvalidationSink with real in-memory catalog & L1 LRU cache."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from config_sync.domain.dtos import (
    ConfigCursor,
    ConfigDeltaEvent,
    ConfigEntityRecord,
    ConfigSnapshot,
)
from config_sync.domain.enums import ConfigChangeAction

from identity.adapters.outbound.cache.in_memory_global_authz_catalog import (
    InMemoryGlobalAuthzCatalog,
)
from identity.adapters.outbound.cache.l1_lru_principal_cache import L1LruPrincipalCache
from identity.adapters.outbound.config_sync.identity_invalidation_sink import (
    IdentityInvalidationSink,
)
from identity.domain.constants import (
    AuthzEffect,
    IdentityConfigEntityType,
    PolicyEngineType,
    TenantIsolationMode,
    TenantTierType,
    UserStatus,
)
from identity.domain.dtos import (
    PrincipalSnapshotDTO,
    RoleDefinitionDTO,
    TenantNodeDTO,
)


@pytest.mark.asyncio
async def test_snapshot_populates_global_catalog_and_advances_cursor() -> None:
    catalog = InMemoryGlobalAuthzCatalog()
    cache = L1LruPrincipalCache()
    sink = IdentityInvalidationSink(global_catalog=catalog, principal_cache=cache)

    assert (
        await sink.get_current_cursor(app_id="identity", tenant_id="platform")
        == ConfigCursor.zero()
    )

    snapshot = ConfigSnapshot(
        app_id="identity",
        tenant_id="platform",
        txid=100,
        version=5,
        checksum="snap-sha",
        entities=(
            ConfigEntityRecord(
                entity_type=IdentityConfigEntityType.TRUSTED_ISSUER.value,
                entity_id="https://idp.example/",
                tenant_id="platform",
                checksum="c1",
                payload={
                    "issuer": "https://idp.example/",
                    "jwks_uri": "https://idp.example/.well-known/jwks",
                    "allowed_audiences": ["soopa-web", 123],
                    "jwks_host_header": "idp.internal",
                    "is_active": True,
                },
            ),
            ConfigEntityRecord(
                entity_type=IdentityConfigEntityType.EMAIL_DOMAIN_ROUTE.value,
                entity_id="acme.com",
                tenant_id="tenant-acme",
                checksum="c2",
                payload={
                    "domain": "ACME.COM",
                    "tenant_id": "tenant-acme",
                    "idp_issuer": "https://sso.acme.com",
                    "idp_realm_name": "acme-realm",
                    "sso_enforced": True,
                    "verified_at": "2026-05-01T12:00:00+00:00",
                },
            ),
            ConfigEntityRecord(
                entity_type=IdentityConfigEntityType.PLATFORM_ROLE.value,
                entity_id="role-platform-admin",
                tenant_id="platform",
                checksum="c3",
                payload={
                    "name": "PlatformAdmin",
                    "capabilities": ["tenant:read", "tenant:write"],
                    "deny_capabilities": ["billing:delete"],
                    "is_system": True,
                },
            ),
            ConfigEntityRecord(
                entity_type=IdentityConfigEntityType.CAPABILITY.value,
                entity_id="tenant:read",
                tenant_id="platform",
                checksum="c4",
                payload={
                    "code": "tenant:read",
                    "domain": "ucp",
                    "resource": "tenant",
                    "action": "read",
                    "display_name": "Read Tenant",
                    "description": "Allows viewing tenant metadata",
                    "is_sensitive": False,
                    "requires_mfa": False,
                    "machine_allowed": True,
                    "tier_scope": "TENANT",
                },
            ),
            ConfigEntityRecord(
                entity_type=IdentityConfigEntityType.POLICY_RULE.value,
                entity_id="rule-mfa-export",
                tenant_id="tenant-acme",
                checksum="c5",
                payload={
                    "engine_type": PolicyEngineType.ABAC.value,
                    "effect": AuthzEffect.DENY.value,
                    "subject_expr": "actor_type == 'HUMAN'",
                    "resource_type": "edi_document",
                    "action_pattern": "edi:export",
                    "condition_json": {"requires_mfa": True},
                    "priority": 10,
                    "is_active": True,
                },
            ),
        ),
    )

    await sink.apply_snapshot(snapshot)

    assert await sink.get_current_cursor(app_id="identity", tenant_id="platform") == ConfigCursor(
        txid=100, version=5
    )

    issuer = catalog.get_trusted_issuer("https://idp.example")
    assert issuer is not None
    assert issuer.allowed_audiences == ("soopa-web",)
    assert issuer.jwks_host_header == "idp.internal"
    assert len(catalog.list_trusted_issuers()) == 1

    route = catalog.get_email_domain_route("acme.com")
    assert route is not None
    assert route.idp_realm_name == "acme-realm"
    assert route.sso_enforced is True
    assert route.verified_at == datetime(2026, 5, 1, 12, 0, tzinfo=UTC)

    role = catalog.get_platform_role("role-platform-admin")
    assert role is not None
    assert role.capabilities == frozenset({"tenant:read", "tenant:write"})
    assert role.deny_capabilities == frozenset({"billing:delete"})

    cap = catalog.get_capability("tenant:read")
    assert cap is not None
    assert cap.domain == "ucp"

    rules = catalog.get_tenant_policy_rules("tenant-acme")
    assert len(rules) == 1
    assert rules[0].id == "rule-mfa-export"
    assert rules[0].effect == AuthzEffect.DENY
    assert rules[0].priority == 10


@pytest.mark.asyncio
async def test_delta_tombstones_evict_l1_caches_and_revoke_jti_immediately() -> None:
    """Security invariant: revocation tombstones must evict targeted L1 entries without collateral impact."""
    catalog = InMemoryGlobalAuthzCatalog()
    cache = L1LruPrincipalCache(max_principals=2, ttl_seconds=60.0)
    sink = IdentityInvalidationSink(global_catalog=catalog, principal_cache=cache)
    now = datetime(2026, 6, 1, tzinfo=UTC)

    await cache.set_principal(
        PrincipalSnapshotDTO(
            user_id="user-1",
            status=UserStatus.ACTIVE,
            tokens_valid_after=now,
            memberships=(),
            role_assignments=(),
        )
    )
    await cache.set_principal(
        PrincipalSnapshotDTO(
            user_id="user-2",
            status=UserStatus.ACTIVE,
            tokens_valid_after=now,
            memberships=(),
            role_assignments=(),
        )
    )
    await cache.set_tenant_node(
        TenantNodeDTO(
            id="tenant-1",
            parent_tenant_id=None,
            hierarchy_path="/tenant-1/",
            tier_type=TenantTierType.ORGANIZATION,
            isolation_mode=TenantIsolationMode.POOLED_REALM,
            status="ACTIVE",
            block_parent_inheritance=False,
            tokens_valid_after=now,
        )
    )
    await cache.set_enabled_apps("tenant-1", frozenset({"edi", "ip"}))
    await cache.set_role_definition(
        RoleDefinitionDTO(
            id="role-1",
            tenant_id="tenant-1",
            name="Operator",
            capabilities=frozenset({"edi:read"}),
        )
    )

    # 1. USER_REVOCATION evicts user-1 & revokes its JTI, leaving user-2 intact
    await sink.apply_delta(
        ConfigDeltaEvent(
            event_id="evt-1",
            app_id="identity",
            tenant_id="tenant-1",
            entity_type=IdentityConfigEntityType.USER_REVOCATION.value,
            entity_id="user-1",
            action=ConfigChangeAction.UPSERT,
            txid=10,
            version=1,
            checksum="d1",
            payload={"jti": "jwt-revoked-abc", "jti_ttl_seconds": 600},
        )
    )
    assert await cache.get_principal("user-1") is None
    assert await cache.get_principal("user-2") is not None
    assert await cache.is_jti_revoked("jwt-revoked-abc") is True
    assert await cache.is_jti_revoked("jwt-other") is False

    # 2. TENANT_UPDATED evicts tenant node
    await sink.apply_delta(
        ConfigDeltaEvent(
            event_id="evt-2",
            app_id="identity",
            tenant_id="tenant-1",
            entity_type=IdentityConfigEntityType.TENANT_UPDATED.value,
            entity_id="tenant-1",
            action=ConfigChangeAction.UPSERT,
            txid=10,
            version=2,
            checksum="d2",
            payload={},
        )
    )
    assert await cache.get_tenant_node("tenant-1") is None

    # 3. SUBSCRIPTION_UPDATED evicts enabled apps
    await sink.apply_delta(
        ConfigDeltaEvent(
            event_id="evt-3",
            app_id="identity",
            tenant_id="tenant-1",
            entity_type=IdentityConfigEntityType.SUBSCRIPTION_UPDATED.value,
            entity_id="sub-1",
            action=ConfigChangeAction.UPSERT,
            txid=10,
            version=3,
            checksum="d3",
            payload={},
        )
    )
    assert await cache.get_enabled_apps("tenant-1") is None

    # 4. ROLE_UPDATED evicts cached role definition
    await sink.apply_delta(
        ConfigDeltaEvent(
            event_id="evt-4",
            app_id="identity",
            tenant_id="tenant-1",
            entity_type=IdentityConfigEntityType.ROLE_UPDATED.value,
            entity_id="role-1",
            action=ConfigChangeAction.UPSERT,
            txid=10,
            version=4,
            checksum="d4",
            payload={},
        )
    )
    assert await cache.get_role_definition("role-1") is None


@pytest.mark.asyncio
async def test_delta_deletes_remove_catalog_entries_and_ignore_stale_cursors() -> None:
    """Monotonicity invariant: stale cursors cannot resurrect deleted IAM catalog entries."""
    catalog = InMemoryGlobalAuthzCatalog()
    cache = L1LruPrincipalCache()
    sink = IdentityInvalidationSink(global_catalog=catalog, principal_cache=cache)

    # Seed entries via initial snapshot at cursor (20, 1)
    await sink.apply_snapshot(
        ConfigSnapshot(
            app_id="identity",
            tenant_id="platform",
            txid=20,
            version=1,
            checksum="s1",
            entities=(
                ConfigEntityRecord(
                    entity_type=IdentityConfigEntityType.TRUSTED_ISSUER.value,
                    entity_id="https://old-idp.example",
                    tenant_id="platform",
                    checksum="i1",
                    payload={"jwks_uri": "https://old-idp.example/jwks"},
                ),
                ConfigEntityRecord(
                    entity_type=IdentityConfigEntityType.EMAIL_DOMAIN_ROUTE.value,
                    entity_id="bad-date.example",
                    tenant_id="tenant-2",
                    checksum="r1",
                    payload={
                        "idp_realm_name": "realm-2",
                        "verified_at": "not-an-iso-timestamp",
                    },
                ),
                ConfigEntityRecord(
                    entity_type=IdentityConfigEntityType.PLATFORM_ROLE.value,
                    entity_id="role-temp",
                    tenant_id="platform",
                    checksum="p1",
                    payload={"name": "TempRole", "capabilities": "not-a-list"},
                ),
                ConfigEntityRecord(
                    entity_type=IdentityConfigEntityType.POLICY_RULE.value,
                    entity_id="rule-temp",
                    tenant_id="tenant-2",
                    checksum="pr1",
                    payload={"priority": "non-int"},
                ),
            ),
        )
    )

    # Malformed verified_at fails closed to None (prevents accidental domain verification!)
    bad_route = catalog.get_email_domain_route("bad-date.example")
    assert bad_route is not None
    assert bad_route.verified_at is None
    temp_role = catalog.get_platform_role("role-temp")
    assert temp_role is not None
    assert temp_role.capabilities == frozenset()

    # Delete all four entity types with strictly increasing cursors
    for version, (entity_type, entity_id, tenant_id) in enumerate(
        (
            (IdentityConfigEntityType.TRUSTED_ISSUER.value, "https://old-idp.example", "platform"),
            (IdentityConfigEntityType.EMAIL_DOMAIN_ROUTE.value, "bad-date.example", "tenant-2"),
            (IdentityConfigEntityType.PLATFORM_ROLE.value, "role-temp", "platform"),
            (IdentityConfigEntityType.POLICY_RULE.value, "rule-temp", "tenant-2"),
        ),
        start=2,
    ):
        await sink.apply_delta(
            ConfigDeltaEvent(
                event_id=f"del-{version}",
                app_id="identity",
                tenant_id=tenant_id,
                entity_type=entity_type,
                entity_id=entity_id,
                action=ConfigChangeAction.DELETE,
                txid=20,
                version=version,
                checksum=f"del-sha-{version}",
                payload={},
            )
        )

    assert catalog.get_trusted_issuer("https://old-idp.example") is None
    assert catalog.get_email_domain_route("bad-date.example") is None
    assert catalog.get_platform_role("role-temp") is None
    assert catalog.get_tenant_policy_rules("tenant-2") == ()

    # Stale/replayed UPSERT at older cursor (20, 3) MUST be ignored and cannot resurrect issuer
    await sink.apply_delta(
        ConfigDeltaEvent(
            event_id="replay-stale",
            app_id="identity",
            tenant_id="platform",
            entity_type=IdentityConfigEntityType.TRUSTED_ISSUER.value,
            entity_id="https://old-idp.example",
            action=ConfigChangeAction.UPSERT,
            txid=20,
            version=3,
            checksum="stale",
            payload={"jwks_uri": "https://old-idp.example/jwks"},
        )
    )
    assert catalog.get_trusted_issuer("https://old-idp.example") is None
