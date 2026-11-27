"""Bounded in-process LRU + TTL PrincipalCachePort implementation (constant ~25MB RAM/pod)."""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Generic, TypeVar

from identity.domain.dtos import PrincipalSnapshotDTO, RoleDefinitionDTO, TenantNodeDTO
from identity.ports.outbound.principal_cache_port import PrincipalCachePort

_V = TypeVar("_V")


class _BoundedTtlLru(Generic[_V]):
    """O(1) bounded LRU map with per-entry monotonic TTL expiration."""

    def __init__(self, *, max_entries: int, default_ttl_seconds: float) -> None:
        self._max_entries = max(1, max_entries)
        self._default_ttl = default_ttl_seconds
        self._store: OrderedDict[str, tuple[_V, float]] = OrderedDict()

    def get(self, key: str) -> _V | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() >= expires_at:
            self._store.pop(key, None)
            return None
        self._store.move_to_end(key)
        return value

    def set(self, key: str, value: _V, *, ttl_seconds: float | None = None) -> None:
        ttl = self._default_ttl if ttl_seconds is None else ttl_seconds
        expires_at = time.monotonic() + ttl
        self._store[key] = (value, expires_at)
        self._store.move_to_end(key)
        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def __len__(self) -> int:
        return len(self._store)


class L1LruPrincipalCache(PrincipalCachePort):
    """Cardinality-safe L1 in-process cache for 50M+ user scale with instant tombstone eviction."""

    def __init__(
        self,
        *,
        max_principals: int = 50_000,
        max_tenants: int = 50_000,
        max_roles: int = 20_000,
        max_revoked_jtis: int = 100_000,
        ttl_seconds: float = 60.0,
    ) -> None:
        self._principals: _BoundedTtlLru[PrincipalSnapshotDTO] = _BoundedTtlLru(
            max_entries=max_principals,
            default_ttl_seconds=ttl_seconds,
        )
        self._tenants: _BoundedTtlLru[TenantNodeDTO] = _BoundedTtlLru(
            max_entries=max_tenants,
            default_ttl_seconds=ttl_seconds,
        )
        self._entitlements: _BoundedTtlLru[frozenset[str]] = _BoundedTtlLru(
            max_entries=max_tenants,
            default_ttl_seconds=ttl_seconds,
        )
        self._roles: _BoundedTtlLru[RoleDefinitionDTO] = _BoundedTtlLru(
            max_entries=max_roles,
            default_ttl_seconds=ttl_seconds,
        )
        self._revoked_jtis: _BoundedTtlLru[bool] = _BoundedTtlLru(
            max_entries=max_revoked_jtis,
            default_ttl_seconds=900.0,
        )

    async def get_principal(self, user_id: str) -> PrincipalSnapshotDTO | None:
        return self._principals.get(user_id)

    async def set_principal(self, snapshot: PrincipalSnapshotDTO) -> None:
        self._principals.set(snapshot.user_id, snapshot)

    async def evict_principal(self, user_id: str) -> None:
        self._principals.delete(user_id)

    async def get_tenant_node(self, tenant_id: str) -> TenantNodeDTO | None:
        return self._tenants.get(tenant_id)

    async def set_tenant_node(self, node: TenantNodeDTO) -> None:
        self._tenants.set(node.id, node)

    async def evict_tenant(self, tenant_id: str) -> None:
        self._tenants.delete(tenant_id)

    async def get_enabled_apps(self, tenant_id: str) -> frozenset[str] | None:
        return self._entitlements.get(tenant_id)

    async def set_enabled_apps(self, tenant_id: str, app_slugs: frozenset[str]) -> None:
        self._entitlements.set(tenant_id, app_slugs)

    async def evict_enabled_apps(self, tenant_id: str) -> None:
        self._entitlements.delete(tenant_id)

    async def get_role_definition(self, role_id: str) -> RoleDefinitionDTO | None:
        return self._roles.get(role_id)

    async def set_role_definition(self, role: RoleDefinitionDTO) -> None:
        self._roles.set(role.id, role)

    async def evict_role(self, role_id: str) -> None:
        self._roles.delete(role_id)

    async def is_jti_revoked(self, jti: str) -> bool:
        return self._revoked_jtis.get(jti) is True

    async def revoke_jti(self, jti: str, ttl_seconds: int) -> None:
        self._revoked_jtis.set(jti, True, ttl_seconds=float(max(1, ttl_seconds)))


__all__ = ["L1LruPrincipalCache"]
