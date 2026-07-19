from typing import Any

from pydantic import AliasChoices, BaseModel, Field, field_validator


class TokenClaims(BaseModel):
    sub: str
    iss: str
    aud: str | list[str]
    exp: int
    iat: int | None = None
    tenant_id: str = Field(validation_alias=AliasChoices("urn:zitadel:iam:org:id", "tenant_id"))
    organization_id: str | None = None
    roles: list[str] = Field(default_factory=list, validation_alias=AliasChoices("urn:zitadel:iam:org:project:roles", "roles"))
    permissions: list[str] = Field(default_factory=list)

    @field_validator("roles", mode="before")
    @classmethod
    def parse_roles(_cls, v: Any) -> list[str]:
        if isinstance(v, dict):
            return list(v.keys())
        if isinstance(v, list):
            return [str(x) for x in v]
        return [str(v)]

    model_config = {"extra": "allow", "populate_by_name": True}


class IdentityContext(BaseModel):
    subject: str
    tenant_id: str
    organization_id: str | None = None
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    claims: dict[str, Any]


def identity_context_from_claims(claims: TokenClaims) -> IdentityContext:
    return IdentityContext(
        subject=claims.sub,
        tenant_id=claims.tenant_id,
        organization_id=claims.organization_id,
        roles=tuple(claims.roles),
        permissions=tuple(claims.permissions),
        claims=claims.model_dump(mode="json"),
    )
