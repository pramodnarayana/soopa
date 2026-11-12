"""Hexagonal outbound port for UCP tenant metadata resolution in the Control Plane."""

from __future__ import annotations

from typing import Protocol

from ip.engine.domain.authorization import TenantSummary


class TenantRepositoryPort(Protocol):
    """Outbound port for resolving UCP Tenant records by federated IdP tenant ID or slug."""

    async def get_by_idp_tenant_id(self, idp_tenant_id: str) -> TenantSummary | None:
        """Resolves an active UCP tenant matching the federated IdP tenant ID."""
        ...

    async def get_by_slug(self, tenant_slug: str) -> TenantSummary | None:
        """Resolves an active (non-deleted) UCP tenant matching the canonical slug."""
        ...


__all__ = ["TenantRepositoryPort"]
