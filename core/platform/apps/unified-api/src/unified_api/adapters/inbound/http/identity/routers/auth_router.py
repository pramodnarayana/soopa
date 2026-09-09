from fastapi import APIRouter, Request
from identity.domain.identity_context import IdentityContext
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["Auth"])


class AuthMeResponse(BaseModel):
    authenticated: bool
    subject: str | None = None
    email: str | None = None
    name: str | None = None
    tenantId: str | None = None
    isPlatformAdmin: bool | None = None
    capabilities: list[str] | None = None
    authorizedTenants: list[str] | None = None


@router.get("/me", response_model=AuthMeResponse)
async def get_me(request: Request) -> AuthMeResponse:
    """
    Returns the currently authenticated user's IdentityContext, including their
    resolved dynamic PBAC capabilities.
    """
    try:
        identity: IdentityContext | None = request.state.identity
    except AttributeError:
        identity = None
    if not identity:
        return AuthMeResponse(authenticated=False)

    return AuthMeResponse(
        authenticated=True,
        subject=identity.subject,
        email=str(identity.claims.get("email")) if identity.claims.get("email") else None,
        name=str(identity.claims.get("name")) if identity.claims.get("name") else None,
        tenantId=identity.tenant_id,
        isPlatformAdmin=identity.is_platform_admin,
        capabilities=sorted(list(identity.capabilities)),
        authorizedTenants=sorted(list(identity.authorized_tenants)),
    )
