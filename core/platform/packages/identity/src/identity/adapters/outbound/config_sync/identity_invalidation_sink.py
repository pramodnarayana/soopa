"""Config-Sync sink applying low-cardinality global IAM updates & high-cardinality cache tombstones."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

import structlog
from config_sync.domain.dtos import ConfigCursor, ConfigDeltaEvent, ConfigSnapshot
from config_sync.domain.enums import ConfigChangeAction
from config_sync.ports.config_apply_sink_port import ConfigApplySinkPort

from identity.domain.authorization import CapabilityDescriptor
from identity.domain.constants import (
    AuthzEffect,
    IdentityConfigEntityType,
    PolicyEngineType,
)
from identity.domain.dtos import (
    EmailDomainRouteDTO,
    PolicyRuleDTO,
    RoleDefinitionDTO,
    TrustedIssuerDTO,
)
from identity.ports.outbound.principal_cache_port import PrincipalCachePort
from identity.ports.outbound.tenant_hierarchy_port import MutableGlobalAuthzCatalogPort

logger = structlog.get_logger(__name__)


def _parse_str_tuple(raw: object) -> tuple[str, ...]:
    if isinstance(raw, list):
        return tuple(str(item) for item in raw if isinstance(item, str))
    return ()


def _parse_optional_dt(raw: object) -> datetime | None:
    if isinstance(raw, str) and raw.strip():
        try:
            return datetime.fromisoformat(raw.strip())
        except ValueError:
            return None
    return None


class IdentityInvalidationSink(ConfigApplySinkPort):
    """Applies low-cardinality global IAM snapshots/deltas and evicts L1/L2 caches in <200ms."""

    def __init__(
        self,
        *,
        global_catalog: MutableGlobalAuthzCatalogPort,
        principal_cache: PrincipalCachePort,
    ) -> None:
        self._catalog = global_catalog
        self._cache = principal_cache
        self._cursor = ConfigCursor.zero()

    async def get_current_cursor(self, *, app_id: str, tenant_id: str) -> ConfigCursor:
        del app_id, tenant_id
        return self._cursor

    async def apply_snapshot(self, snapshot: ConfigSnapshot) -> None:
        for entity in snapshot.entities:
            await self._apply_record(
                entity_type=entity.entity_type,
                entity_id=entity.entity_id,
                tenant_id=entity.tenant_id,
                action=ConfigChangeAction.UPSERT,
                payload=entity.payload,
            )
        self._cursor = snapshot.cursor
        logger.info(
            "identity_config_snapshot_applied",
            cursor=snapshot.cursor.encode(),
            entity_count=len(snapshot.entities),
        )

    async def apply_delta(self, delta: ConfigDeltaEvent) -> None:
        if delta.cursor <= self._cursor:
            return
        await self._apply_record(
            entity_type=delta.entity_type,
            entity_id=delta.entity_id,
            tenant_id=delta.tenant_id,
            action=delta.action,
            payload=delta.payload,
        )
        self._cursor = delta.cursor

    async def _apply_record(
        self,
        *,
        entity_type: str,
        entity_id: str,
        tenant_id: str,
        action: ConfigChangeAction,
        payload: Mapping[str, object],
    ) -> None:
        # High-cardinality invalidation tombstones (<200ms cache eviction, zero global RAM bloat!)
        if entity_type == IdentityConfigEntityType.USER_REVOCATION.value:
            await self._cache.evict_principal(entity_id)
            raw_jti = payload.get("jti")
            raw_ttl = payload.get("jti_ttl_seconds")
            if isinstance(raw_jti, str) and raw_jti:
                ttl = int(raw_ttl) if isinstance(raw_ttl, int) else 900
                await self._cache.revoke_jti(raw_jti, ttl)
            return

        if entity_type == IdentityConfigEntityType.TENANT_UPDATED.value:
            await self._cache.evict_tenant(entity_id)
            return

        if entity_type == IdentityConfigEntityType.SUBSCRIPTION_UPDATED.value:
            await self._cache.evict_enabled_apps(tenant_id)
            return

        if entity_type == IdentityConfigEntityType.ROLE_UPDATED.value:
            await self._cache.evict_role(entity_id)
            return

        # Low-cardinality global RAM catalog updates
        self._apply_global_catalog_record(
            entity_type=entity_type,
            entity_id=entity_id,
            tenant_id=tenant_id,
            action=action,
            payload=payload,
        )

    def _apply_global_catalog_record(
        self,
        *,
        entity_type: str,
        entity_id: str,
        tenant_id: str,
        action: ConfigChangeAction,
        payload: Mapping[str, object],
    ) -> None:
        if entity_type == IdentityConfigEntityType.TRUSTED_ISSUER.value:
            if action == ConfigChangeAction.DELETE:
                self._catalog.remove_trusted_issuer(entity_id)
            else:
                host_hdr = payload.get("jwks_host_header")
                self._catalog.upsert_trusted_issuer(
                    TrustedIssuerDTO(
                        issuer=str(payload.get("issuer") or entity_id),
                        jwks_uri=str(payload.get("jwks_uri") or ""),
                        allowed_audiences=_parse_str_tuple(payload.get("allowed_audiences")),
                        jwks_host_header=host_hdr if isinstance(host_hdr, str) else None,
                        is_active=bool(payload.get("is_active", True)),
                    )
                )
            return

        if entity_type == IdentityConfigEntityType.EMAIL_DOMAIN_ROUTE.value:
            if action == ConfigChangeAction.DELETE:
                self._catalog.remove_email_domain_route(entity_id)
            else:
                self._catalog.upsert_email_domain_route(
                    EmailDomainRouteDTO(
                        domain=str(payload.get("domain") or entity_id),
                        tenant_id=str(payload.get("tenant_id") or tenant_id),
                        idp_issuer=str(payload.get("idp_issuer") or ""),
                        idp_realm_name=str(payload.get("idp_realm_name") or ""),
                        sso_enforced=bool(payload.get("sso_enforced", False)),
                        verified_at=_parse_optional_dt(payload.get("verified_at")),
                    )
                )
            return

        if entity_type == IdentityConfigEntityType.PLATFORM_ROLE.value:
            if action == ConfigChangeAction.DELETE:
                self._catalog.remove_platform_role(entity_id)
            else:
                self._catalog.upsert_platform_role(
                    RoleDefinitionDTO(
                        id=entity_id,
                        tenant_id=str(payload.get("tenant_id") or tenant_id),
                        name=str(payload.get("name") or ""),
                        capabilities=frozenset(_parse_str_tuple(payload.get("capabilities"))),
                        deny_capabilities=frozenset(
                            _parse_str_tuple(payload.get("deny_capabilities"))
                        ),
                        is_system=bool(payload.get("is_system", True)),
                    )
                )
            return

        if entity_type == IdentityConfigEntityType.CAPABILITY.value:
            self._catalog.upsert_capability(
                CapabilityDescriptor(
                    code=str(payload.get("code") or entity_id),
                    domain=str(payload.get("domain") or ""),
                    resource=str(payload.get("resource") or ""),
                    action=str(payload.get("action") or ""),
                    display_name=str(payload.get("display_name") or ""),
                    description=str(payload.get("description") or ""),
                    is_sensitive=bool(payload.get("is_sensitive", False)),
                    requires_mfa=bool(payload.get("requires_mfa", False)),
                    machine_allowed=bool(payload.get("machine_allowed", True)),
                    tier_scope=str(payload.get("tier_scope") or "TENANT"),
                )
            )
            return

        if entity_type == IdentityConfigEntityType.POLICY_RULE.value:
            if action == ConfigChangeAction.DELETE:
                self._catalog.remove_policy_rule(tenant_id=tenant_id, rule_id=entity_id)
            else:
                raw_cond = payload.get("condition_json")
                cond_dict = dict(raw_cond) if isinstance(raw_cond, dict) else {}
                raw_prio = payload.get("priority")
                self._catalog.upsert_policy_rule(
                    PolicyRuleDTO(
                        id=entity_id,
                        tenant_id=tenant_id,
                        engine_type=PolicyEngineType(
                            str(payload.get("engine_type") or PolicyEngineType.ABAC.value)
                        ),
                        effect=AuthzEffect(str(payload.get("effect") or AuthzEffect.ALLOW.value)),
                        subject_expr=str(payload.get("subject_expr") or "*"),
                        resource_type=str(payload.get("resource_type") or "*"),
                        action_pattern=str(payload.get("action_pattern") or "*"),
                        condition_json=cond_dict,
                        priority=int(raw_prio) if isinstance(raw_prio, int) else 100,
                        is_active=bool(payload.get("is_active", True)),
                    )
                )


__all__ = ["IdentityInvalidationSink"]
