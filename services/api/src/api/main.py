import logging
from contextlib import asynccontextmanager
from typing import Any

from config.settings import get_settings
from database.connection import DatabaseRouter
from fastapi import Depends, FastAPI
from identity.dependencies import get_current_tenant_id, get_tenant_session
from sqlalchemy.ext.asyncio import AsyncSession

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


@app.get("/api/me", tags=["Identity"])
async def get_me(
    tenant_id: int = Depends(get_current_tenant_id),
    session: AsyncSession = Depends(get_tenant_session),
) -> Any:
    """
    Returns the current user's resolved tenant_id and verifies database access.
    """
    # Simply hitting the database to prove we have a valid, RLS-secured session
    from sqlalchemy import text

    result = await session.execute(text("SELECT current_setting('app.current_tenant')"))
    current_rls_tenant = result.scalar()

    return {"status": "success", "tenant_id": tenant_id, "rls_enforced_tenant": current_rls_tenant}
