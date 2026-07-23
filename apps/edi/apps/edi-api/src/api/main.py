import logging
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv

from api.dependencies.auth import get_current_tenant_id, get_current_user_profile
from api.dependencies.database import get_tenant_session

load_dotenv()
logging.basicConfig(level=logging.INFO)

from config.settings import get_settings
from database.connection import DatabaseRouter
from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api import cdc_relay
from api.routers import (
    edi_headers,
    edi_json,
    edi_tools,
    explorer,
    routes,
    trading_partners,
    transactions,
    webhooks,
)
from api.routers import (
    platform as platform_admin,
)
from api.routers.developers import api_tokens
from api.routers.trading_partners import as2_receive, platform

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
    errors = exc.errors()
    sanitized_errors = []
    for error in errors:
        error_dict = dict(error)
        error_dict.pop("input", None)
        error_dict.pop("url", None)
        # 'ctx' may contain the raw exception object, which is not JSON-serializable.
        ctx = error_dict.pop("ctx", None)
        if ctx:
            error_dict["ctx"] = {k: str(v) for k, v in ctx.items()}
        sanitized_errors.append(error_dict)

    logger.error(f"422 Error at {request.url.path}: {sanitized_errors}")
    return JSONResponse(
        status_code=422,
        content={"detail": sanitized_errors},
    )


app.include_router(cdc_relay.router)
app.include_router(trading_partners.router)
app.include_router(webhooks.router)
app.include_router(platform.router)
app.include_router(platform_admin.router)
app.include_router(routes.router)
app.include_router(edi_headers.router)
app.include_router(edi_tools.router)
app.include_router(as2_receive.router, prefix="/api/v1")
app.include_router(edi_json.router)
app.include_router(api_tokens.router)
app.include_router(transactions.router)
app.include_router(explorer.router)


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
