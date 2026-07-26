from typing import Any

from fastapi import APIRouter, Depends

from api.dependencies.auth import get_current_user_profile

router = APIRouter(prefix="/dashboard", tags=["tenant_dashboard"])


@router.get("", response_model=dict)
async def get_dashboard_data(
    profile: dict[str, Any] = Depends(get_current_user_profile),
) -> dict[str, Any]:

    return {
        "status": "active",
        "tenant_id": profile.get("tenant_id"),
        "rls_enforced_tenant": profile.get("rls_enforced_tenant"),
    }
