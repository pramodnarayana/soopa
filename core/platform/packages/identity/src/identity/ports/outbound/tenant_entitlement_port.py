"""Outbound port inverting multi-app subscription entitlements (zero identity -> ucp coupling)."""

from __future__ import annotations

from typing import Protocol


class TenantEntitlementPort(Protocol):
    """Provides active application slugs subscribed by a tenant (implemented by UCP)."""

    async def get_enabled_app_slugs(self, *, tenant_id: str) -> frozenset[str]: ...

    async def is_app_enabled(self, *, tenant_id: str, app_slug: str) -> bool: ...


__all__ = ["TenantEntitlementPort"]
