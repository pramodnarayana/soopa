"""Domain authorization models, standard roles, and granular resource permissions for IP."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from identity.domain.authorization import Capability, StandardRole
from identity.domain.identity_context import IdentityContext

IpPermission = Capability
IpRole = StandardRole


@dataclass(frozen=True)
class TenantSummary:
    """Pure domain value object representing a resolved UCP tenant."""

    id: str
    slug: str
    idp_tenant_id: str | None
    name: str


IP_ROLE_CAPABILITIES: Mapping[str, frozenset[str]] = {
    StandardRole.CUSTOMER_SUPPORT.value: frozenset(
        {
            Capability.IP_RECORDS_CANONICAL_READ.value,
            Capability.IP_RECORDS_RAW_READ.value,
            Capability.IP_TRACES_READ.value,
            Capability.IP_SYNC_TRIGGER.value,
            Capability.IP_FLOWS_READ.value,
        }
    ),
    StandardRole.CUSTOMER.value: frozenset(
        {
            Capability.IP_RECORDS_CANONICAL_READ.value,
            Capability.IP_TRACES_READ.value,
            Capability.IP_FLOWS_READ.value,
        }
    ),
    StandardRole.VIEWER.value: frozenset(
        {
            Capability.IP_RECORDS_CANONICAL_READ.value,
            Capability.IP_TRACES_READ.value,
        }
    ),
    StandardRole.TENANT_ADMIN.value: frozenset(
        {
            Capability.TENANT_ADMIN.value,
            Capability.IP_RECORDS_CANONICAL_READ.value,
            Capability.IP_RECORDS_RAW_READ.value,
            Capability.IP_TRACES_READ.value,
            Capability.IP_SYNC_TRIGGER.value,
            Capability.IP_FLOWS_READ.value,
            Capability.IP_FLOWS_WRITE.value,
            Capability.IP_FLOWS_EXECUTE.value,
        }
    ),
}


def _candidate_tenant_keys(
    identity: IdentityContext,
    raw_target: str | None,
) -> tuple[str, ...]:
    """Builds deduplicated tenant lookup keys across forward and reverse `tenant_mapping` entries."""
    if not raw_target:
        return ()
    keys: list[str] = [raw_target]
    for source_key, mapped_val in identity.tenant_mapping.items():
        if source_key == raw_target and mapped_val not in keys:
            keys.append(str(mapped_val))
        elif mapped_val == raw_target and source_key not in keys:
            keys.append(str(source_key))
    return tuple(keys)


def _resolve_scoped_roles(
    identity: IdentityContext,
    tenant_id: str | None,
) -> tuple[str, ...]:
    """Resolves role names applicable to `tenant_id` (including federated `tenant_mapping` keys)."""
    if not identity.tenant_roles:
        return identity.roles

    raw_target = tenant_id or identity.tenant_id
    resolved: list[str] = []
    for key in _candidate_tenant_keys(identity, raw_target):
        resolved.extend(identity.tenant_roles.get(key, ()))
    return tuple(resolved)


def resolve_effective_capabilities(
    identity: IdentityContext, tenant_id: str | None = None
) -> frozenset[str]:
    """Resolves all granular capabilities granted to the identity from direct capabilities, permissions, or roles scoped to tenant_id."""
    if identity.is_platform_admin:
        return frozenset(c.value for c in Capability)

    caps = set(identity.capabilities)
    caps.update(identity.permissions)

    if Capability.TENANT_ADMIN.value in caps:
        caps.update(IP_ROLE_CAPABILITIES[StandardRole.TENANT_ADMIN.value])

    for role_name in _resolve_scoped_roles(identity, tenant_id):
        matched = IP_ROLE_CAPABILITIES.get(role_name)
        if matched:
            caps.update(matched)

    return frozenset(caps)


def has_ip_capability(
    identity: IdentityContext, capability: Capability | str, tenant_id: str | None = None
) -> bool:
    """Checks whether the identity holds the requested discrete resource capability for the specified tenant."""
    cap_val = capability.value if isinstance(capability, Capability) else str(capability)
    if identity.is_platform_admin:
        return True
    effective = resolve_effective_capabilities(identity, tenant_id=tenant_id)
    return cap_val in effective


has_ip_permission = has_ip_capability


__all__ = [
    "IP_ROLE_CAPABILITIES",
    "Capability",
    "IpPermission",
    "IpRole",
    "StandardRole",
    "TenantSummary",
    "has_ip_capability",
    "has_ip_permission",
    "resolve_effective_capabilities",
]
