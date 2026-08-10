from typing import Any

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator


class TokenClaims(BaseModel):
    sub: str
    iss: str
    aud: str | list[str]
    exp: int
    iat: int | None = None
    tenant_id: str | None = Field(
        default=None, validation_alias=AliasChoices("tenant_id", "urn:zitadel:iam:org:id")
    )
    organization_id: str | None = None
    authorized_tenants: set[str] = Field(default_factory=set)
    roles: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("urn:zitadel:iam:org:project:roles", "roles"),
    )
    permissions: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def extract_authorized_tenants(cls, data: Any) -> Any:
        authorized_tenants = set()
        if isinstance(data, dict):
            # 1. Primary injected org (if Action is enabled)
            # Prioritize the internal Canonical ID ('tenant_id') over the IdP Org ID
            tenant_id = data.get("tenant_id") or data.get("urn:zitadel:iam:org:id")
            if tenant_id:
                authorized_tenants.add(str(tenant_id))

            # Add the IdP Org ID as well so legacy mapping still works
            idp_org_id = data.get("urn:zitadel:iam:org:id")
            if idp_org_id:
                authorized_tenants.add(str(idp_org_id))

            # 2. Derive cryptographically from Role allocations (Zero Trust stateless ACL)
            roles_dict = data.get("urn:zitadel:iam:org:project:roles") or data.get("roles")
            if isinstance(roles_dict, dict):
                for orgs in roles_dict.values():
                    if isinstance(orgs, dict):
                        for org_id in orgs:
                            authorized_tenants.add(str(org_id))

            # NOTE: The canonical ID "ten_000000000000000000000000" is used as a reserved sentinel value to represent
            # platform-admin privileges. Downstream code checks for
            # exact match of this ID in authorized_tenants to grant platform-wide access.
            # This is an intentional convention and not a verification of the actual
            # Zitadel instance-owner organization ID.

            data["authorized_tenants"] = list(authorized_tenants)
        return data

    @field_validator("roles", mode="before")
    @classmethod
    def parse_roles(_cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, dict):
            return list(v.keys())
        if isinstance(v, list):
            return [str(x) for x in v]
        return [str(v)]

    model_config = {"extra": "allow", "populate_by_name": True}


# The canonical tenant ID used to represent the global platform administrator scope.
PLATFORM_TENANT_ID = "ten_000000000000000000000000"

M2M_API_KEY_PREFIX = "sp_api_"


class IdentityContext(BaseModel):
    subject: str
    tenant_id: str | None = None
    organization_id: str | None = None
    authorized_tenants: set[str] = Field(default_factory=set)
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    claims: dict[str, Any]

    @property
    def is_platform_admin(self) -> bool:
        """True when the identity has an admin role explicitly assigned to the platform-admin sentinel tenant ID."""
        if PLATFORM_TENANT_ID not in self.authorized_tenants:
            return False

        roles_dict = self.claims.get("urn:zitadel:iam:org:project:roles") or self.claims.get(
            "roles"
        )
        if isinstance(roles_dict, dict):
            for role, orgs in roles_dict.items():
                if (
                    role in ("admin", "platform-admin")
                    and isinstance(orgs, dict)
                    and PLATFORM_TENANT_ID in orgs
                ):
                    return True

        # If roles is a flat list, just check if they have admin and the platform tenant ID is authorized (fallback)
        return bool(
            isinstance(roles_dict, list)
            and any(r in roles_dict for r in ("admin", "platform-admin"))
        )


def identity_context_from_claims(claims: TokenClaims) -> IdentityContext:
    return IdentityContext(
        subject=claims.sub,
        tenant_id=claims.tenant_id,
        organization_id=claims.organization_id,
        authorized_tenants=claims.authorized_tenants,
        roles=tuple(claims.roles),
        permissions=tuple(claims.permissions),
        claims=claims.model_dump(mode="json"),
    )
