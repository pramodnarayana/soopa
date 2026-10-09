from collections.abc import MutableMapping
from typing import Any, cast

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from identity.domain.identity_context import PLATFORM_TENANT_ID, IdentityContext
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.routing import Match, Mount
from starlette.types import ASGIApp

logger = structlog.get_logger(__name__)

# Paths that require a valid authentication token, but inherently DO NOT have a Tenant ID context.
# Used for exact-match routes like profile discovery or global platform management.
_TENANT_EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        "/api/v1/auth/me",
        "/api/v1/tenants",  # GET all tenants, POST create tenant
        "/api/v1/tenants/roles",  # GET all global roles
        "/api/v1/apps",  # GET all global apps
    }
)


class TenantContextMiddleware(BaseHTTPMiddleware):
    """
    ASGI Middleware: Resolves the active Tenant ID for the request and validates
    that the authenticated IdentityContext is authorized to access it.

    This runs after the AuthenticationMiddleware. It extracts the tenant context
    from the x-tenant-id header (for Gateway UI requests) or from the IdentityContext
    directly (for M2M API Keys), and sets `request.state.tenant_id`.
    """

    def __init__(
        self,
        app: ASGIApp,
        public_paths: frozenset[str],
        tenant_exempt_paths: frozenset[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.public_paths = public_paths
        self.tenant_exempt_paths = tenant_exempt_paths or frozenset()

    def _extract_tenant_id_from_route(
        self, router: ASGIApp, scope: MutableMapping[str, Any]
    ) -> str | None:
        """
        Recursively traverses the FastAPI/Starlette routing tree to resolve the route
        for the current request and extract the `tenant_id` path parameter.
        This provides a robust, enterprise-grade fallback for dynamic endpoints
        without hardcoding URL path string manipulation.
        """
        if not hasattr(router, "routes"):
            return None

        for route in router.routes:
            match, child_scope = route.matches(scope)
            if match == Match.FULL:
                if isinstance(route, Mount):
                    new_scope = dict(scope)
                    new_scope.update(child_scope)
                    return self._extract_tenant_id_from_route(route.app, new_scope)
                else:
                    return cast(str | None, child_scope.get("path_params", {}).get("tenant_id"))
        return None

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
        # Path parameter (extracted dynamically from the routing tree).
        # IdentityContext (identity.tenant_id) is the primary fallback for M2M API requests.

        path_tenant_id = self._extract_tenant_id_from_route(request.app.router, request.scope)

        active_tenant_id = (
            request.headers.get("x-tenant-id")
            or request.query_params.get("tenant_id")
            or path_tenant_id
            or identity.tenant_id
        )

        # Always set it on state so we never throw AttributeError later
        request.state.tenant_id = active_tenant_id

        # ONLY exempt exact-match routes that inherently lack a tenant context
        normalized_path = request.url.path.rstrip("/")
        is_exempt = normalized_path in self.tenant_exempt_paths

        if not active_tenant_id:
            if is_exempt:
                return await call_next(request)
            logger.warning(
                "[TENANT_CONTEXT_MIDDLEWARE] Tenant ID missing from request. path=%s is_exempt=%s",
                request.url.path,
                is_exempt,
            )
            return JSONResponse(
                status_code=400,
                content={"detail": "Tenant ID missing from request."},
            )

        # 2. Validate Authorization
        is_platform_admin = (
            "PlatformAdmin" in identity.roles or PLATFORM_TENANT_ID in identity.authorized_tenants
        )

        if (
            not is_platform_admin
            and active_tenant_id not in identity.authorized_tenants
            and not is_exempt
        ):
            logger.warning(
                "[TENANT_CONTEXT_MIDDLEWARE] Identity {identity_subject} attempted to access unauthorized tenant {active_tenant_id}.",
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

        return await call_next(request)
