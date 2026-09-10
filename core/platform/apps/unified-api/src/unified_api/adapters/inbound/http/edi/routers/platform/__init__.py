from fastapi import APIRouter, Depends

from unified_api.adapters.inbound.http.dependencies.edi.auth import require_platform_admin

router = APIRouter(prefix="/api/v1/platform", dependencies=[Depends(require_platform_admin)])

__all__ = ["router"]
