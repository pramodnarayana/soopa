"""Hexagonal outbound port for UCP tenant metadata resolution in the Control Plane."""

from __future__ import annotations

from typing import Protocol

from ip.engine.domain.authorization import TenantSummary


class TenantRepositoryPort(Protocol):
    """Outbound port for resolving UCP Tenant records by dedicated IdP realm or slug."""

    async def get_by_idp_realm(self, idp_realm_name: str) -> TenantSummary | None:
        """Resolves an active dedicated-realm UCP tenant matching the IdP realm name."""
        ...

    async def get_by_slug(self, tenant_slug: str) -> TenantSummary | None:
        """Resolves an active (non-deleted) UCP tenant matching the canonical slug."""
        ...


__all__ = ["TenantRepositoryPort"]
