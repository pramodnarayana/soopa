from typing import Any

from pydantic import BaseModel, Field


class TokenClaims(BaseModel):
    sub: str
    iss: str
    aud: str | list[str]
    exp: int
    iat: int | None = None
    tenant_id: str
    organization_id: str | None = None
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)

    model_config = {"extra": "allow"}


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
