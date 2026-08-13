"""
Unified API Shell — Composition Root.

This is the single public HTTP entrypoint for the Soopa Modular Monolith.
It wires together all domain modules into one deployable process.

Architectural invariants:
  1. CORS lives ONLY here — sub-app middleware stacks are isolated from the
     parent; the browser's preflight OPTIONS request never reaches a mounted
     sub-app's middleware chain.
  2. This module is the ONLY place allowed to import from multiple domains
     (UCP and EDI) simultaneously.
  3. Domain modules (ucp, edi) must never import from each other directly.
     Cross-domain communication flows exclusively through the Port/Adapter
     contract defined in ucp.ports.outbound.edi_service.IEdiService.
"""

import collections.abc
import contextlib

from edi.adapters.inbound.ucp_adapter import UcpAdapter
from edi.module import create_edi_app
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ucp.adapters.inbound.http.middleware.authentication import _PUBLIC_PATHS
from ucp.adapters.inbound.http.routers import (
    apps_router,
    tenants_router,
    tokens_router,
    users_router,
)
from ucp.adapters.outbound.database.postgres_api_token_repository import PostgresApiTokenRepository
from ucp.adapters.outbound.database.tenant_repository import TenantRepository
from ucp.application.services.authenticators.api_key_strategy import ApiKeyStrategy
from ucp.application.services.authenticators.jwt_strategy import JwtStrategy
from ucp.bootstrap.container import Container as UcpContainer
from ucp.core.container import _async_session_maker, get_token_verifier
from ucp.ports.outbound.edi_service import IEdiService

from unified_api.bootstrap.exceptions import setup_shell_exception_handlers
from unified_api.bootstrap.lifespan import shell_lifespan
from unified_api.bootstrap.middleware import AuthenticationMiddleware, TenantContextMiddleware
from unified_api.bootstrap.observability import setup_observability

# ---------------------------------------------------------------------------
# Shell (Host) Application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Unified Platform API (Host)",
    description="The centralized composition root for the modular monolith.",
    version="1.0.0",
    lifespan=shell_lifespan,
)
setup_observability(app)

# ---------------------------------------------------------------------------
# Middlewares are added in LIFO (Last In, First Out) order.
# The LAST middleware added will be the FIRST one to execute.
#
# Intended Execution Order: CORS -> Authentication -> Tenant Context -> Route
# Therefore, we add them in reverse order: Tenant Context -> Authentication -> CORS
# ---------------------------------------------------------------------------

# Layer 3 — Tenant Context Resolution
# Once authenticated, this middleware explicitly resolves the active Tenant ID
# for the request and validates authorization against the IdentityContext.
app.add_middleware(TenantContextMiddleware, public_paths=_PUBLIC_PATHS)


# Layer 2 — Perimeter Authentication
# The authentication middleware runs once per request at the Shell boundary.
# It uses the Strategy Pattern to dynamically evaluate different token types
# (M2M API Keys, IdP JWTs) without needing modification when adding new methods.
@contextlib.asynccontextmanager
async def api_token_repo_factory() -> collections.abc.AsyncIterator[PostgresApiTokenRepository]:
    async with _async_session_maker() as session:
        yield PostgresApiTokenRepository(session)


@contextlib.asynccontextmanager
async def tenant_repo_factory() -> collections.abc.AsyncIterator[TenantRepository]:
    async with _async_session_maker() as session:
        yield TenantRepository(session)


app.add_middleware(
    AuthenticationMiddleware,
    strategies=[
        ApiKeyStrategy(token_repo_factory=api_token_repo_factory),
        JwtStrategy(
            tenant_repo_factory=tenant_repo_factory,
            token_verifier=get_token_verifier(),
        ),
    ],
    public_paths=_PUBLIC_PATHS,
)

# Layer 1 — CORS (outermost, handles all browser preflight requests)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server (UCP dashboard)
        "http://localhost:3001",  # EDI UI dev server (alternative port)
        "http://localhost:3000",  # Fallback / legacy
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Layer 4 — Shell-level Exception Handlers (covers all domains)
# ---------------------------------------------------------------------------
setup_shell_exception_handlers(app)

# ---------------------------------------------------------------------------
# UCP Domain — inline router inclusion
#
# UCP routers are included DIRECTLY on the Shell (not as a sub-app mount) so
# their paths resolve to /api/v1/tenants/..., /api/v1/users/..., /api/v1/apps/...
# — exactly as the frontend expects (VITE_UCP_API_URL = http://localhost:3000).
#
# UCP dependency injection (real adapters → router placeholders) is wired here
# on the Shell app instance, since that is the app that owns the UCP routes.
# ---------------------------------------------------------------------------
from notification.api.in_app_notifications_router import (  # type: ignore[import-untyped]
    router as in_app_notifications_router,
)
from notification.api.preferences_router import router as notification_preferences_router  # type: ignore[import-untyped]
from notification.api.templates_router import router as notification_templates_router  # type: ignore[import-untyped]

app.include_router(tenants_router.router, prefix="/api/v1")
app.include_router(users_router.router, prefix="/api/v1")
app.include_router(apps_router.router, prefix="/api/v1")
app.include_router(tokens_router.router, prefix="/api/v1/tenants/{tenant_id}/tokens")
app.include_router(in_app_notifications_router)
app.include_router(notification_preferences_router)
app.include_router(notification_templates_router)

ucp_container = UcpContainer()
app.state.ucp_container = ucp_container


# ---------------------------------------------------------------------------
# Cross-Domain Contract Wiring (Ports & Adapters)
#
# UCP declares the outbound Port (IEdiService).
# EDI provides the inbound Adapter (UcpAdapter).
# The Shell is the composition root — the ONLY layer that resolves this binding.
# ---------------------------------------------------------------------------
def get_edi_service() -> IEdiService:
    return UcpAdapter()


app.dependency_overrides[IEdiService] = get_edi_service

# ---------------------------------------------------------------------------
# EDI Domain — sub-application mounted at root
#
# EDI routers self-prefix their paths (/api/v1/platform/..., /api/v1/tenants/{id}/edi/...).
# Mounting at root preserves these URLs unchanged for the frontend.
#
# EDI is mounted AFTER UCP routers are registered so Starlette resolves
# explicit UCP paths first and delegates all unmatched paths to EDI.
# ---------------------------------------------------------------------------
edi_app = create_edi_app()
app.mount("/", edi_app)


@app.get("/health", tags=["System"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "architecture": "modular_monolith"}
