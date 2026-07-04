import logging
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from config.settings import get_settings
from database.connection import DatabaseRouter
from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from identity.dependencies import get_current_tenant_id, get_tenant_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api import cdc_relay
from api.dependencies import get_current_user_profile
from api.routers import routes, trading_partners, webhooks
from api.routers.trading_partners import platform

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    settings = get_settings()

    logger.info("Initializing DatabaseRouter for API Service")
    db_router = DatabaseRouter(
        settings.database.global_url,
        pool_size=settings.database.pool_size,
        max_overflow=settings.database.max_overflow,
    )
    app.state.db_router = db_router

    yield

    logger.info("Shutting down DatabaseRouter")
    await db_router.close_all()


settings = get_settings()

app = FastAPI(
    title="EDI AS2 Platform API",
    description="Main gateway for the EDI AS2 Platform",
    version="1.0.0",
    lifespan=lifespan,
    swagger_ui_oauth2_redirect_url="/docs/oauth2-redirect",
    swagger_ui_init_oauth={
        "clientId": settings.identity.oauth_client_id,
        "appName": "EDI AS2 Platform API",
        "usePkceWithAuthorizationCodeGrant": True,
        "scopes": "openid profile email",
    },
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    import json

    body = await request.body()
    try:
        parsed = json.loads(body)
    except Exception:
        parsed = body
    print("\n" + "=" * 50)
    print("422 Error - Unprocessable Content")
    print(f"Path: {request.url.path}")
    print(f"Payload: {parsed}")
    print(f"Validation Errors: {exc.errors()}")
    print("=" * 50 + "\n")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )


app.include_router(cdc_relay.router)
app.include_router(trading_partners.router)
app.include_router(webhooks.router)
app.include_router(platform.router)
app.include_router(routes.router)


@app.get("/api/me", tags=["Identity"])
async def get_me(
    tenant_id: int = Depends(get_current_tenant_id),
    session: AsyncSession = Depends(get_tenant_session),
    profile: dict[str, Any] = Depends(get_current_user_profile),
) -> Any:
    """
    Returns the current user's resolved tenant_id, role, feature flags, and verifies database access.
    """
    # 1. Verify RLS (Data Plane isolation)
    rls_result = await session.execute(text("SELECT current_setting('app.current_tenant')"))
    current_rls_tenant = rls_result.scalar()

    if str(current_rls_tenant) != str(tenant_id):
        raise HTTPException(status_code=403, detail="RLS context mismatch. Unauthorized access.")

    return profile
