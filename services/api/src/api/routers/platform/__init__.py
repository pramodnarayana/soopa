from fastapi import APIRouter, Depends

from api.dependencies import require_platform_admin

from .scheduler import router as scheduler_router

router = APIRouter(prefix="/api/v1/platform", dependencies=[Depends(require_platform_admin)])
router.include_router(scheduler_router)

__all__ = ["router"]
