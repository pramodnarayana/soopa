"""
Unified API Shell — Composition Root.

This is the single public HTTP entrypoint for the Soopa Modular Monolith.
It wires together Core Platform capabilities (`ucp`, `identity`, `notification`)
and dynamically loads enabled business bounded contexts (`ip`, `edi`) via
`LaunchableApiModule` plugins configured by `ENABLED_APPS`.
"""

from __future__ import annotations

import collections.abc
import contextlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from identity.adapters.outbound.database.api_token_repository import PostgresApiTokenRepository
from identity.adapters.outbound.database.role_repository import PostgresRoleRepository
from identity.adapters.outbound.database.user_repository import PostgresUserRepository
from ucp.adapters.outbound.database.tenant_repository import TenantRepository
from ucp.application.use_cases.authenticators.api_key_strategy import ApiKeyStrategy
from ucp.application.use_cases.authenticators.jwt_strategy import JwtStrategy
from ucp.bootstrap.container import Container as UcpContainer
from ucp.bootstrap.dependencies import get_token_verifier

from unified_api.adapters.inbound.http.identity.routers import (
    auth_router,
    tokens_router,
)
from unified_api.adapters.inbound.http.middleware.authentication import _PUBLIC_PATHS
from unified_api.adapters.inbound.http.middleware.tenant_context import _TENANT_EXEMPT_PATHS
from unified_api.adapters.inbound.http.notifications.routers.in_app_notifications_router import (
    router as in_app_notifications_router,
)
from unified_api.adapters.inbound.http.notifications.routers.notification_preferences_router import (
    router as notification_preferences_router,
)
from unified_api.adapters.inbound.http.notifications.routers.notification_templates_router import (
    router as notification_templates_router,
)
from unified_api.adapters.inbound.http.notifications.routers.notification_user_preferences_router import (
    router as notification_user_preferences_router,
)
from unified_api.adapters.inbound.http.ucp.routers import (
    apps_router,
    tenants_router,
    users_router,
    webhooks_router,
)
from unified_api.bootstrap.exceptions import setup_shell_exception_handlers
from unified_api.bootstrap.lifespan import shell_lifespan
from unified_api.bootstrap.middleware import AuthenticationMiddleware, TenantContextMiddleware
from unified_api.bootstrap.observability import setup_observability
from unified_api.registry import load_enabled_api_modules
from unified_api.settings import get_settings


def create_app(enabled_apps: str | None = None) -> FastAPI:
    """Creates and configures the Unified API Shell application."""
    settings = get_settings()
    resolved_enabled_apps = enabled_apps if enabled_apps is not None else settings.enabled_apps

    shell = FastAPI(
        title="Unified Platform API (Host)",
        description="The centralized composition root for the modular monolith.",
        version="1.0.0",
        lifespan=shell_lifespan,
    )
    shell.state.settings = settings
    setup_observability(shell)

    # Layer 3 — Tenant Context Resolution
    shell.add_middleware(
        TenantContextMiddleware,
        public_paths=_PUBLIC_PATHS,
        tenant_exempt_paths=_TENANT_EXEMPT_PATHS,
    )

    # Layer 2 — Perimeter Authentication
    @contextlib.asynccontextmanager
    async def api_token_repo_factory() -> collections.abc.AsyncIterator[PostgresApiTokenRepository]:
        async with shell.state.db_provider.session() as session:
            yield PostgresApiTokenRepository(session)

    @contextlib.asynccontextmanager
    async def tenant_repo_factory() -> collections.abc.AsyncIterator[TenantRepository]:
        async with shell.state.db_provider.session() as session:
            yield TenantRepository(session)

    @contextlib.asynccontextmanager
    async def user_repo_factory() -> collections.abc.AsyncIterator[PostgresUserRepository]:
        async with shell.state.db_provider.session() as session:
            yield PostgresUserRepository(session)

    @contextlib.asynccontextmanager
    async def role_repo_factory() -> collections.abc.AsyncIterator[PostgresRoleRepository]:
        async with shell.state.db_provider.session() as session:
            yield PostgresRoleRepository(session)

    shell.add_middleware(
        AuthenticationMiddleware,
        strategies=[
            ApiKeyStrategy(token_repo_factory=api_token_repo_factory),
            JwtStrategy(
                tenant_repo_factory=tenant_repo_factory,
                user_repo_factory=user_repo_factory,
                role_repo_factory=role_repo_factory,
                token_verifier=get_token_verifier(),
            ),
        ],
        public_paths=_PUBLIC_PATHS,
    )

    # Layer 1 — CORS (outermost, handles all browser preflight requests)
    shell.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Layer 4 — Shell-level Exception Handlers (covers all domains)
    setup_shell_exception_handlers(shell)

    # Core Platform Routers (UCP, Identity, Notification)
    shell.include_router(auth_router.router, prefix="/api/v1")
    shell.include_router(tenants_router.router, prefix="/api/v1")
    shell.include_router(users_router.router, prefix="/api/v1")
    shell.include_router(apps_router.router, prefix="/api/v1")
    shell.include_router(tokens_router.router, prefix="/api/v1/tenants/{tenant_id}/tokens")
    shell.include_router(webhooks_router.router)
    shell.include_router(in_app_notifications_router)
    shell.include_router(notification_preferences_router)
    shell.include_router(notification_templates_router)
    shell.include_router(notification_user_preferences_router)

    ucp_container = UcpContainer()
    shell.state.ucp_container = ucp_container

    # Health Check (registered BEFORE bounded-context mounts)
    @shell.get("/health", tags=["System"])
    def health_check() -> dict[str, str]:
        return {
            "status": "ok",
            "architecture": "modular_monolith",
            "enabled_apps": ",".join(m.name for m in shell.state.api_modules),
        }

    # Dynamically load and mount enabled bounded-context API modules
    api_modules = load_enabled_api_modules(resolved_enabled_apps)
    shell.state.api_modules = api_modules
    for module in api_modules:
        module.register_routes(shell)

    return shell


app = create_app()
edi_app: FastAPI | None = app.state.edi_app if "edi_app" in app.state._state else None
