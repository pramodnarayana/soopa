from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TokenClaims:
    sub: str
    iss: str
    aud: str | list[str]
    exp: int
    iat: int | None = None
    tenant_id: str | None = None
    organization_id: str | None = None
    authorized_tenants: set[str] = field(default_factory=set)
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    tenant_roles: dict[str, list[str]] = field(default_factory=dict)
    raw_claims: dict[str, Any] = field(default_factory=dict)


# The canonical tenant ID used to represent the global platform administrator scope.
PLATFORM_TENANT_ID = "ten_000000000000000000000000"

M2M_API_KEY_PREFIX = "sp_api_"


@dataclass(frozen=True)
class IdentityContext:
    subject: str
    claims: dict[str, Any]
    tenant_id: str | None = None
    organization_id: str | None = None
    authorized_tenants: set[str] = field(default_factory=set)
    tenant_mapping: dict[str, str] = field(default_factory=dict)
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    tenant_roles: dict[str, list[str]] = field(default_factory=dict)
    capabilities: set[str] = field(default_factory=set)

    @property
    def is_platform_admin(self) -> bool:
        """True when the identity has an admin role explicitly assigned to the platform-admin sentinel tenant ID."""
        if PLATFORM_TENANT_ID not in self.authorized_tenants:
            return False

        for org_id, roles in self.tenant_roles.items():
            if any(r.lower() in ("admin", "platform-admin", "platformadmin") for r in roles) and (
                org_id == PLATFORM_TENANT_ID
                or self.tenant_mapping.get(org_id) == PLATFORM_TENANT_ID
            ):
                # Only grant platform admin if the specific org they are an admin for
                # is explicitly cryptographically mapped to the PLATFORM_TENANT_ID
                return True

        return False


def identity_context_from_claims(
    claims: TokenClaims, tenant_mapping: dict[str, str] | None = None
) -> IdentityContext:
    """
    Constructs an IdentityContext from validated token claims.

    Args:
        claims: Validated token claims (provider-agnostic)
        tenant_mapping: Optional mapping from IdP org IDs to canonical tenant IDs.
                       Used for platform-admin role validation.
    """
    return IdentityContext(
        subject=claims.sub,
        tenant_id=claims.tenant_id,
        organization_id=claims.organization_id,
        authorized_tenants=claims.authorized_tenants,
        tenant_mapping=tenant_mapping or {},
        roles=tuple(claims.roles),
        permissions=tuple(claims.permissions),
        tenant_roles=claims.tenant_roles,
        capabilities=set(),
        claims=claims.raw_claims,
    )
