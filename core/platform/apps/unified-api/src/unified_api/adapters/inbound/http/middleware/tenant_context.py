import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from identity.domain.identity_context import PLATFORM_TENANT_ID, IdentityContext
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

logger = structlog.get_logger(__name__)


class TenantContextMiddleware(BaseHTTPMiddleware):
    """
    ASGI Middleware: Resolves the active Tenant ID for the request and validates
    that the authenticated IdentityContext is authorized to access it.

    This runs after the AuthenticationMiddleware. It extracts the tenant context
    from the x-tenant-id header (for Gateway UI requests) or from the IdentityContext
    directly (for M2M API Keys), and sets `request.state.tenant_id`.
    """

    def __init__(self, app: ASGIApp, public_paths: frozenset[str]) -> None:
        super().__init__(app)
        self.public_paths = public_paths

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in self.public_paths:
            return await call_next(request)

        # Retrieve the IdentityContext populated by AuthenticationMiddleware
        identity: IdentityContext | None = getattr(request.state, "identity", None)
        if not identity:
            # If no identity exists, either it failed authentication (and was ignored to let a guard catch it),
            # or it's a completely unauthenticated route. We don't enforce tenant context here if there's no identity.
            return await call_next(request)

        # 1. Resolve Active Tenant ID
        # Header (x-tenant-id) is injected by API Gateway for UI requests.
        # Query parameter (tenant_id) is used as a fallback for EventSource (SSE) which cannot send headers.
        # IdentityContext (identity.tenant_id) is the primary fallback for M2M API requests.
        active_tenant_id = (
            request.headers.get("x-tenant-id")
            or request.query_params.get("tenant_id")
            or identity.tenant_id
        )

        if not active_tenant_id:
            logger.warning("[TENANT_CONTEXT_MIDDLEWARE] Tenant ID missing from request.")
            return JSONResponse(
                status_code=400,
                content={"detail": "Tenant ID missing from request."},
            )

        # 2. Validate Authorization
        is_platform_admin = (
            "PlatformAdmin" in identity.roles or PLATFORM_TENANT_ID in identity.authorized_tenants
        )

        if not is_platform_admin and active_tenant_id not in identity.authorized_tenants:
            logger.warning(
                "[TENANT_CONTEXT_MIDDLEWARE] Identity {identity.subject} attempted to access unauthorized tenant {active_tenant_id}.",
                identity_subject=identity.subject,
                active_tenant_id=active_tenant_id,
            )
            return JSONResponse(
                status_code=403,
                content={"detail": f"Token does not grant access to tenant {active_tenant_id}."},
            )

        # 3. Inject Context
        logger.debug(
            "[TENANT_CONTEXT_MIDDLEWARE] Active Tenant resolved: {active_tenant_id}",
            active_tenant_id=active_tenant_id,
        )
        request.state.tenant_id = active_tenant_id

        return await call_next(request)
