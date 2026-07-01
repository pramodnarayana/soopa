from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["ops"])


@router.get("/health")
async def health() -> Any:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> Any:
    if getattr(request.app.state, "db_router", None) is None:
        raise HTTPException(status_code=503, detail="Database router not initialized")
    if getattr(request.app.state, "s3_storage", None) is None:
        raise HTTPException(status_code=503, detail="S3 Storage not initialized")
    return {"status": "ready"}


@router.get("/metrics")
async def metrics() -> Any:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
