from fastapi import APIRouter, Depends

from api.dependencies.auth import require_platform_admin

router = APIRouter(prefix="/api/v1/platform", dependencies=[Depends(require_platform_admin)])

__all__ = ["router"]
