"""Pure multi-tier tenant hierarchy (`ltree`) validation and inheritance evaluation."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime

from seedwork.domain.exceptions import Result

from identity.domain.constants import MembershipScope, MembershipStatus
from identity.domain.dtos import MembershipDTO, TenantNodeDTO, UserRoleAssignmentDTO
from identity.domain.exceptions import IdentityError, IdentityErrorCode
from identity.domain.identity_context import PLATFORM_TENANT_ID

_LTREE_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,255}$")


def validate_ltree_label(label: str) -> Result[str, IdentityError]:
    """Validate that a tenant identifier is safe for PostgreSQL `ltree` path labels."""
    cleaned = label.strip()
    if not _LTREE_LABEL_PATTERN.match(cleaned):
        return Result.fail(
            IdentityError(
                code=IdentityErrorCode.INVALID_HIERARCHY_LABEL,
                message=(
                    f"Hierarchy label '{label}' contains characters invalid for PostgreSQL ltree "
                    "(only ASCII letters, digits, and underscores are permitted)."
                ),
                details={"label": label},
            )
        )
    return Result.ok(cleaned)


def build_hierarchy_path(
    *,
    parent_path: str | None,
    tenant_id: str,
) -> Result[str, IdentityError]:
    """Build a validated PostgreSQL `ltree` materialized path for a tenant node."""
    label_res = validate_ltree_label(tenant_id)
    if label_res.is_err:
        return label_res
    label = label_res.unwrap()

    if parent_path is None or not parent_path.strip():
        return Result.ok(label)

    segments = [seg for seg in parent_path.strip().split(".") if seg]
    for seg in segments:
        seg_res = validate_ltree_label(seg)
        if seg_res.is_err:
            return seg_res
    if label in segments:
        return Result.fail(
            IdentityError(
                code=IdentityErrorCode.HIERARCHY_CYCLE_DETECTED,
                message=f"Tenant '{label}' is already an ancestor in path '{parent_path}'.",
                details={"tenant_id": label, "parent_path": parent_path},
            )
        )
    return Result.ok(".".join((*segments, label)))


def detect_hierarchy_cycle(*, target_path: str, candidate_parent_path: str) -> bool:
    """Return True if reparenting `target_path` under `candidate_parent_path` creates a cycle."""
    target_segments = tuple(s for s in target_path.strip().split(".") if s)
    parent_segments = tuple(s for s in candidate_parent_path.strip().split(".") if s)
    if not target_segments or not parent_segments:
        return False
    if len(parent_segments) < len(target_segments):
        return False
    return parent_segments[: len(target_segments)] == target_segments


def parse_ancestor_ids(hierarchy_path: str) -> tuple[str, ...]:
    """Return ordered tenant IDs from root (index 0) down to leaf (index -1)."""
    return tuple(seg for seg in hierarchy_path.strip().split(".") if seg)


def resolve_inheritable_ancestors(
    *,
    nodes_by_id: Mapping[str, TenantNodeDTO],
    target_tenant_id: str,
) -> tuple[TenantNodeDTO, ...]:
    """Return ordered `(target, parent, ...)` nodes from which permissions may inherit.

    Traverses upward from `target_tenant_id` along its `hierarchy_path`, stopping as soon as a
    node sets `block_parent_inheritance = True` (preserving strict subsidiary isolation).
    """
    target = nodes_by_id.get(target_tenant_id)
    if target is None:
        return ()

    ancestor_ids = parse_ancestor_ids(target.hierarchy_path)
    if not ancestor_ids or ancestor_ids[-1] != target_tenant_id:
        ancestor_ids = (*ancestor_ids, target_tenant_id)

    inheritable: list[TenantNodeDTO] = []
    # Walk from leaf (target) upward toward root
    for tenant_id in reversed(ancestor_ids):
        node = nodes_by_id.get(tenant_id)
        if node is None:
            continue
        inheritable.append(node)
        if node.block_parent_inheritance:
            break
    return tuple(inheritable)


def is_membership_active(membership: MembershipDTO, *, now: datetime) -> bool:
    """True when membership status is ACTIVE and has not expired."""
    if membership.status != MembershipStatus.ACTIVE:
        return False
    return not (membership.expires_at is not None and membership.expires_at <= now)


def is_role_assignment_active(assignment: UserRoleAssignmentDTO, *, now: datetime) -> bool:
    """True when a role assignment has not expired."""
    return not (assignment.expires_at is not None and assignment.expires_at <= now)


def resolve_effective_tenant_scopes(
    *,
    memberships: Sequence[MembershipDTO],
    inheritable_chain: Sequence[TenantNodeDTO],
    target_tenant_id: str,
    now: datetime,
) -> frozenset[str]:
    """Return the set of tenant IDs whose roles apply to `target_tenant_id`.

    - Target tenant matches both `DIRECT` and `SUBTREE` memberships.
    - Inheritable ancestor tenants match ONLY `SUBTREE` memberships (or `PLATFORM_TENANT_ID`
      when explicitly held with `SUBTREE` scope).
    """
    active_by_tenant: dict[str, MembershipDTO] = {
        m.tenant_id: m for m in memberships if is_membership_active(m, now=now)
    }
    matched_tenants: set[str] = set()

    for node in inheritable_chain:
        membership = active_by_tenant.get(node.id)
        if membership is None:
            continue
        if node.id == target_tenant_id or membership.scope == MembershipScope.SUBTREE:
            matched_tenants.add(node.id)

    # Platform subtree administrators always retain audited platform scope visibility
    platform_membership = active_by_tenant.get(PLATFORM_TENANT_ID)
    if platform_membership is not None and platform_membership.scope == MembershipScope.SUBTREE:
        matched_tenants.add(PLATFORM_TENANT_ID)

    return frozenset(matched_tenants)


def resolve_effective_role_ids(
    *,
    role_assignments: Sequence[UserRoleAssignmentDTO],
    effective_tenant_ids: frozenset[str],
    now: datetime,
) -> tuple[str, ...]:
    """Collect active, deduplicated role IDs granted within `effective_tenant_ids`."""
    seen: set[str] = set()
    ordered: list[str] = []
    for assignment in role_assignments:
        if assignment.tenant_id not in effective_tenant_ids:
            continue
        if not is_role_assignment_active(assignment, now=now):
            continue
        if assignment.role_id not in seen:
            seen.add(assignment.role_id)
            ordered.append(assignment.role_id)
    return tuple(ordered)


__all__ = [
    "build_hierarchy_path",
    "detect_hierarchy_cycle",
    "is_membership_active",
    "is_role_assignment_active",
    "parse_ancestor_ids",
    "resolve_effective_role_ids",
    "resolve_effective_tenant_scopes",
    "resolve_inheritable_ancestors",
    "validate_ltree_label",
]
