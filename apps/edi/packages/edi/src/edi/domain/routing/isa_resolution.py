"""Pure domain value objects and resolution rules for mapping EDI ISA pairs to tenants."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class IsaResolutionStatus(StrEnum):
    """Structured outcome for resolving a tenant from an inbound EDI ISA sender/receiver pair."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    PLATFORM_ONLY = "PLATFORM_ONLY"


@dataclass(frozen=True)
class IsaRouteCandidate:
    """Pure projection of a non-deleted inbound route matching an ISA sender/receiver pair."""

    route_id: str
    tenant_id: str
    name: str | None
    active: bool
    transaction_type: str | None = None


@dataclass(frozen=True)
class IsaTenantResolution:
    """First-class result describing how an ISA pair maps to tenant inbound routes."""

    status: IsaResolutionStatus
    tenant_id: str | None = None
    matched_tenant_ids: tuple[str, ...] = ()
    inactive_route_ids: tuple[str, ...] = ()
    inactive_route_names: tuple[str, ...] = ()


def resolve_isa_candidates(
    candidates: Sequence[IsaRouteCandidate],
    *,
    platform_tenant_id: str,
    transaction_type: str | None = None,
) -> IsaTenantResolution:
    """Pure domain resolution algorithm mapping matching inbound route candidates to a tenant.

    Invariants:
      1. When ``transaction_type`` is provided, only routes matching that exact
         ``transaction_type`` or wildcard routes (``transaction_type is None``) are eligible.
      2. Active customer-tenant routes take precedence over inactive routes.
      3. Multiple distinct customer tenants (whether active or inactive) always return AMBIGUOUS
         to guarantee strict cross-tenant isolation.
      4. Routes owned exclusively by the platform sentinel return PLATFORM_ONLY.
      5. Single-tenant inactive routes return INACTIVE with the owning ``tenant_id`` and route
         metadata so the payload can be durably persisted as RECEIVED with a RouteNotActiveEdiError.
    """
    eligible = (
        [
            c
            for c in candidates
            if c.transaction_type is None or c.transaction_type == transaction_type
        ]
        if transaction_type is not None
        else list(candidates)
    )
    if not eligible:
        return IsaTenantResolution(status=IsaResolutionStatus.NOT_FOUND)

    active_tenants = sorted({c.tenant_id for c in eligible if c.active})
    if active_tenants:
        non_platform_active = [t for t in active_tenants if t != platform_tenant_id]
        if not non_platform_active:
            return IsaTenantResolution(
                status=IsaResolutionStatus.PLATFORM_ONLY,
                matched_tenant_ids=tuple(active_tenants),
            )
        if len(non_platform_active) > 1:
            return IsaTenantResolution(
                status=IsaResolutionStatus.AMBIGUOUS,
                matched_tenant_ids=tuple(non_platform_active),
            )
        return IsaTenantResolution(
            status=IsaResolutionStatus.ACTIVE,
            tenant_id=non_platform_active[0],
            matched_tenant_ids=tuple(non_platform_active),
        )

    inactive_tenants = sorted({c.tenant_id for c in eligible})
    non_platform_inactive = [t for t in inactive_tenants if t != platform_tenant_id]
    if not non_platform_inactive:
        return IsaTenantResolution(
            status=IsaResolutionStatus.PLATFORM_ONLY,
            matched_tenant_ids=tuple(inactive_tenants),
        )
    if len(non_platform_inactive) > 1:
        return IsaTenantResolution(
            status=IsaResolutionStatus.AMBIGUOUS,
            matched_tenant_ids=tuple(non_platform_inactive),
        )

    owning_tenant = non_platform_inactive[0]
    tenant_candidates = [c for c in eligible if c.tenant_id == owning_tenant]
    inactive_ids = tuple(sorted(c.route_id for c in tenant_candidates))
    inactive_names = tuple(
        sorted(c.name.strip() for c in tenant_candidates if c.name and c.name.strip())
    )
    return IsaTenantResolution(
        status=IsaResolutionStatus.INACTIVE,
        tenant_id=owning_tenant,
        matched_tenant_ids=(owning_tenant,),
        inactive_route_ids=inactive_ids,
        inactive_route_names=inactive_names,
    )
