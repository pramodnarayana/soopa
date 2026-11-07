"""Domain authorization models, standard roles, and granular resource permissions for IP."""

from __future__ import annotations

from collections.abc import Mapping

from identity.domain.authorization import Capability, StandardRole
from identity.domain.identity_context import IdentityContext

IpPermission = Capability
IpRole = StandardRole

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

    target_tenant = tenant_id or identity.tenant_id
    if identity.tenant_roles:
        if target_tenant and target_tenant in identity.tenant_roles:
            for r in identity.tenant_roles[target_tenant]:
                matched = IP_ROLE_CAPABILITIES.get(r)
                if matched:
                    caps.update(matched)
    else:
        for r in identity.roles:
            matched = IP_ROLE_CAPABILITIES.get(r)
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
    "has_ip_capability",
    "has_ip_permission",
    "resolve_effective_capabilities",
]
