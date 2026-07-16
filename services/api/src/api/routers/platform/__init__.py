from fastapi import APIRouter

from .scheduler import router as scheduler_router

router = APIRouter(prefix="/api/v1/platform")
router.include_router(scheduler_router)

__all__ = ["router"]
