from typing import Any

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator


class TokenClaims(BaseModel):
    sub: str
    iss: str
    aud: str | list[str]
    exp: int
    iat: int | None = None
    tenant_id: str | None = Field(default=None, validation_alias=AliasChoices("urn:zitadel:iam:org:id", "tenant_id"))
    organization_id: str | None = None
    authorized_tenants: set[str] = Field(default_factory=set)
    roles: list[str] = Field(default_factory=list, validation_alias=AliasChoices("urn:zitadel:iam:org:project:roles", "roles"))
    permissions: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def extract_authorized_tenants(cls, data: Any) -> Any:
        authorized_tenants = set()
        if isinstance(data, dict):
            # 1. Primary injected org (if Action is enabled)
            tenant_id = data.get("urn:zitadel:iam:org:id") or data.get("tenant_id")
            if tenant_id:
                authorized_tenants.add(str(tenant_id))

            # 2. Derive cryptographically from Role allocations (Zero Trust stateless ACL)
            roles_dict = data.get("urn:zitadel:iam:org:project:roles") or data.get("roles")
            if isinstance(roles_dict, dict):
                for orgs in roles_dict.values():
                    if isinstance(orgs, dict):
                        for org_id in orgs:
                            authorized_tenants.add(str(org_id))

            # NOTE: The string "0" is used as a reserved sentinel value to represent
            # platform-admin/instance-owner privileges. Downstream code checks for
            # exact match of "0" in authorized_tenants to grant platform-wide access.
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


class IdentityContext(BaseModel):
    subject: str
    tenant_id: str | None = None
    organization_id: str | None = None
    authorized_tenants: set[str] = Field(default_factory=set)
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    claims: dict[str, Any]


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
