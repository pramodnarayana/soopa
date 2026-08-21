from typing import Any

from fastapi import APIRouter, Depends

from unified_api.adapters.inbound.http.dependencies.edi.auth import get_current_user_profile

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/edi/dashboard", tags=["tenant_dashboard"])


@router.get("", response_model=dict)
async def get_dashboard_data(
    profile: dict[str, Any] = Depends(get_current_user_profile),
) -> dict[str, Any]:

    return {
        "status": "active",
        "tenant_id": profile.get("tenant_id"),
        "rls_enforced_tenant": profile.get("rls_enforced_tenant"),
    }
