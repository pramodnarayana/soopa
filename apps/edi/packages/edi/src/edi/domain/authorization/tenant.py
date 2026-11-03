"""Strongly-typed global tenant authorization and identity value objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class TenantFeatureFlags:
    """Tenant-scoped feature flags evaluated by AuthorizationService."""

    allow_private_as2: bool = False


@dataclass(frozen=True, kw_only=True)
class TenantSummary:
    """Read-only projection of a global tenant identity."""

    id: str
    idp_tenant_id: str | None
    name: str


__all__ = ["TenantFeatureFlags", "TenantSummary"]
