from typing import Any

from fastapi import APIRouter, Request
from identity.domain.identity_context import IdentityContext

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.get("/me")
async def get_me(request: Request) -> dict[str, Any]:
    """
    Returns the currently authenticated user's IdentityContext, including their
    resolved dynamic PBAC capabilities.
    """
    identity: IdentityContext | None = getattr(request.state, "identity", None)
    if not identity:
        return {"authenticated": False}

    return {
        "authenticated": True,
        "subject": identity.subject,
        "email": identity.claims.get("email"),
        "name": identity.claims.get("name"),
        "tenantId": identity.tenant_id,
        "isPlatformAdmin": identity.is_platform_admin,
        "capabilities": list(identity.capabilities),
        "authorizedTenants": list(identity.authorized_tenants),
    }
