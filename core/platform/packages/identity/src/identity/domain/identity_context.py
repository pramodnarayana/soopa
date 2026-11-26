from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field

from seedwork.domain.types import JsonDict


@dataclass(frozen=True)
class TokenClaims:
    sub: str
    iss: str
    aud: str | list[str]
    exp: int
    iat: int | None = None
    jti: str | None = None
    email: str | None = None
    email_verified: bool = False
    idp_realm: str | None = None
    acr: str | None = None
    amr: tuple[str, ...] = ()
    impersonator_subject: str | None = None
    impersonation_ticket_id: str | None = None
    token_scopes: frozenset[str] | None = None
    tenant_id: str | None = None
    organization_id: str | None = None
    authorized_tenants: set[str] = field(default_factory=set)
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    tenant_roles: Mapping[str, list[str]] = field(default_factory=dict)
    tenant_mapping: Mapping[str, str] = field(default_factory=dict)
    raw_claims: JsonDict = field(default_factory=dict)


# The canonical tenant ID used to represent the global platform administrator scope.
PLATFORM_TENANT_ID = "ten_000000000000000000000000"
PLATFORM_ADMIN_CAPABILITY = "platform:admin"

M2M_API_KEY_PREFIX = "sp_api_"
M2M_CLIENT_ID_PREFIX = "cli_"
M2M_CLIENT_SECRET_PREFIX = "sec_"  # noqa: S105 - Identifier prefix constant for M2M client secrets, not a secret value


@dataclass(frozen=True)
class IdentityContext:
    subject: str
    claims: JsonDict
    tenant_id: str | None = None
    organization_id: str | None = None
    authorized_tenants: set[str] = field(default_factory=set)
    tenant_mapping: MutableMapping[str, str] = field(default_factory=dict)
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    tenant_roles: Mapping[str, list[str]] = field(default_factory=dict)
    capabilities: set[str] = field(default_factory=set)

    @property
    def is_platform_admin(self) -> bool:
        """True ONLY when the principal is an authorized member of PLATFORM_TENANT_ID and holds
        either the DB-authoritative `platform:admin` capability or a mapped platform admin role."""
        if PLATFORM_TENANT_ID not in self.authorized_tenants:
            return False

        if PLATFORM_ADMIN_CAPABILITY in self.capabilities:
            return True

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
    claims: TokenClaims, tenant_mapping: MutableMapping[str, str] | None = None
) -> IdentityContext:
    """
    Constructs an IdentityContext from validated token claims.

    Args:
        claims: Validated token claims (provider-agnostic)
        tenant_mapping: Optional mapping from IdP org IDs to canonical tenant IDs.
                       Used for platform-admin role validation.
    """
    combined_mapping = dict(claims.tenant_mapping)
    if tenant_mapping:
        combined_mapping.update(tenant_mapping)

    return IdentityContext(
        subject=claims.sub,
        tenant_id=claims.tenant_id,
        organization_id=claims.organization_id,
        authorized_tenants=claims.authorized_tenants,
        tenant_mapping=combined_mapping,
        roles=tuple(claims.roles),
        permissions=tuple(claims.permissions),
        tenant_roles=claims.tenant_roles,
        capabilities=set(),
        claims=claims.raw_claims,
    )
