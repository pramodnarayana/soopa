import logging
from contextlib import asynccontextmanager
from typing import Any

from config.settings import get_settings
from database.connection import DatabaseRouter
from database.session import get_global_session
from fastapi import Depends, FastAPI, HTTPException
from identity.dependencies import get_current_tenant_id, get_raw_jwt, get_tenant_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api import cdc_relay
from api.adapters.repository import SqlAlchemyTenantRepository
from api.core.authorization import AuthorizationService
from api.routers import partners, platform_partners, routes

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

app.include_router(cdc_relay.router)
app.include_router(partners.router)
app.include_router(platform_partners.router)
app.include_router(routes.router)


@app.get("/api/me", tags=["Identity"])
async def get_me(
    tenant_id: int = Depends(get_current_tenant_id),
    session: AsyncSession = Depends(get_tenant_session),
    global_session: AsyncSession = Depends(get_global_session),
    token_payload: dict[str, Any] = Depends(get_raw_jwt),
) -> Any:
    """
    Returns the current user's resolved tenant_id, role, feature flags, and verifies database access.
    """
    # 1. Verify RLS (Data Plane isolation)
    rls_result = await session.execute(text("SELECT current_setting('app.current_tenant')"))
    current_rls_tenant = rls_result.scalar()

    if str(current_rls_tenant) != str(tenant_id):
        raise HTTPException(status_code=403, detail="RLS context mismatch. Unauthorized access.")

    # 2. Get Authorization Profile via Service
    tenant_repo = SqlAlchemyTenantRepository(global_session)
    auth_service = AuthorizationService(tenant_repo)

    profile = await auth_service.get_authorization_profile(
        tenant_id=tenant_id, token_payload=token_payload, current_rls_tenant=current_rls_tenant
    )

    # The tenant_id is securely resolved from the database via get_current_tenant_id.
    # Therefore, we do not need to check for a custom token claim here.
    return profile
