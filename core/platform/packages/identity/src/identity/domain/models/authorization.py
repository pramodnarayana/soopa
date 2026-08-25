from dataclasses import dataclass, field
from enum import StrEnum

from ucp.domain.events import RoleCreatedEvent
from ucp.domain.models.aggregate_root import AggregateRoot


class Capability(StrEnum):
    """
    Standard dynamic capabilities representing discrete permissions across the platform.
    These map to PostgreSQL arrays inside the Identity Roles table.
    """

    # Global / Platform capabilities
    PLATFORM_ADMIN = "platform:admin"  # Grants full control over everything

    # Tenant Management
    TENANT_ADMIN = "tenant:admin"  # Grants full control over a specific tenant
    TENANT_SETTINGS_READ = "tenant_settings:read"
    TENANT_SETTINGS_WRITE = "tenant_settings:write"

    # Identity & Access Management (IAM)
    USERS_READ = "users:read"
    USERS_WRITE = "users:write"
    ROLES_READ = "roles:read"
    ROLES_WRITE = "roles:write"

    # Integration
    API_KEYS_READ = "api_keys:read"
    API_KEYS_WRITE = "api_keys:write"
    WEBHOOKS_READ = "webhooks:read"
    WEBHOOKS_WRITE = "webhooks:write"

    # Business Domains
    INVOICES_READ = "invoices:read"
    INVOICES_WRITE = "invoices:write"


class StandardRole(StrEnum):
    """
    Standard out-of-the-box roles that should be seeded.
    """

    PLATFORM_ADMIN = "PlatformAdmin"
    TENANT_ADMIN = "TenantAdmin"
    VIEWER = "Viewer"
    DEVELOPER = "Developer"


@dataclass(kw_only=True)
class Role(AggregateRoot):
    """
    Domain entity representing a PBAC Role.
    """

    id: str
    tenant_id: str | None
    name: str
    description: str | None
    capabilities: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__init__()

    @classmethod
    def create(
        cls,
        id: str,
        tenant_id: str | None,
        name: str,
        description: str | None,
        capabilities: list[str],
    ) -> "Role":
        role = cls(
            id=id,
            tenant_id=tenant_id,
            name=name,
            description=description,
            capabilities=capabilities,
        )
        role.add_domain_event(
            RoleCreatedEvent(
                role_id=role.id,
                name=role.name,
                capabilities=tuple(role.capabilities),
            )
        )
        return role
