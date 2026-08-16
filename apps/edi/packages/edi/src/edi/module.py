from typing import Any

import structlog
from dotenv import load_dotenv

from edi.dependencies.auth import get_current_tenant_id, get_current_user_profile
from edi.dependencies.database import get_tenant_session

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# Managed centrally by the Unified API Shell (composition root).
# Do not configure root loggers or StreamHandlers here.
# ---------------------------------------------------------------------------

from config.settings import get_settings
from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from edi import cdc_relay
from edi.bootstrap.container import Container
from edi.bootstrap.lifespan import edi_lifespan
from edi.core.exceptions import OrchestrationError, VaultError
from edi.routers import (
    edi_headers,
    edi_json,
    edi_tools,
    explorer,
    routes,
    trading_partners,
    transactions,
)
from edi.routers import (
    platform as platform_admin,
)
from edi.routers.tenant import dashboard
from edi.routers.trading_partners import as2_receive, platform

logger = structlog.get_logger(__name__)


def create_edi_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="EDI AS2 Platform API",
        description="Main gateway for the EDI AS2 Platform",
        version="1.0.0",
        lifespan=edi_lifespan,
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

        logger.error(
            "422 Error at {request.url.path}: {sanitized_errors}",
            request_url_path=request.url.path,
            sanitized_errors=sanitized_errors,
        )
        return JSONResponse(
            status_code=422,
            content={"detail": sanitized_errors},
        )

    @app.exception_handler(OrchestrationError)
    async def orchestration_exception_handler(
        request: Request, exc: OrchestrationError
    ) -> JSONResponse:
        logger.error(
            "OrchestrationError at {request.url.path}: {exc}",
            request_url_path=request.url.path,
            exc=exc,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc)},
        )

    @app.exception_handler(VaultError)
    async def vault_exception_handler(request: Request, exc: VaultError) -> JSONResponse:
        logger.error(
            "VaultError at {request.url.path}: {exc}", request_url_path=request.url.path, exc=exc
        )
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc)},
        )

    app.include_router(cdc_relay.router)
    app.include_router(trading_partners.router)
    app.include_router(platform.router)
    app.include_router(platform_admin.router)
    app.include_router(routes.router)
    app.include_router(edi_headers.router)
    app.include_router(edi_tools.router, prefix="/api/v1")
    app.include_router(as2_receive.router, prefix="/api/v1")
    app.include_router(edi_json.router)
    app.include_router(transactions.router)
    app.include_router(explorer.router)
    app.include_router(dashboard.router)

    @app.get("/api/me", tags=["Identity"])
    async def get_me(
        tenant_id: str = Depends(get_current_tenant_id),
        session: AsyncSession = Depends(get_tenant_session),  # noqa: B008
        profile: dict[str, Any] = Depends(get_current_user_profile),  # noqa: B008
    ) -> Any:
        """
        Returns the current user's resolved tenant_id, role, feature flags, and verifies database access.
        """
        # 1. Verify RLS (Data Plane isolation)
        rls_result = await session.execute(text("SELECT current_setting('app.current_tenant')"))
        current_rls_tenant = rls_result.scalar()

        if str(current_rls_tenant) != tenant_id:
            raise HTTPException(
                status_code=403, detail="RLS context mismatch. Unauthorized access."
            )

        return profile

    container = Container()
    app.container = container  # type: ignore[attr-defined]

    return app
