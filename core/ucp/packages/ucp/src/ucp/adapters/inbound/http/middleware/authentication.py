"""
Global Authentication Middleware.

Validates the Bearer token exactly ONCE at the perimeter for every inbound
request. The resolved ``IdentityContext`` is attached to ``request.state.identity``
and ``request.scope['identity']`` so all downstream guards and domain auth
dependencies can simply read from it.

Architecture note:
  This is the outermost shell of the Hexagonal Architecture: the HTTP edge.
  It uses the Strategy Pattern to evaluate different token types dynamically.
"""

from collections.abc import Sequence

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from identity.application.authenticate import AuthenticationError, TenantNotProvisionedError
from identity.domain.authentication_strategy import IAuthenticationStrategy
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

logger = structlog.get_logger(__name__)

# Paths that are fully public — no token required.
_PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/docs",
        "/openapi.json",
        "/redoc",
        "/docs/oauth2-redirect",
        "/health",
    }
)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """
    ASGI middleware: validates the auth token once per request and populates
    ``request.state.identity`` and ``request.scope['identity']``.
    """

    def __init__(
        self,
        app: ASGIApp,
        strategies: Sequence[IAuthenticationStrategy],
        public_paths: frozenset[str],
    ) -> None:
        super().__init__(app)
        self.strategies = strategies
        self.public_paths = public_paths

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        logger.error(
            "[AUTH_MIDDLEWARE] Intercepted request for path: {request.url.path}",
            request_url_path=request.url.path,
        )

        if request.url.path in self.public_paths:
            return await call_next(request)

        authorization = request.headers.get("Authorization")
        token = ""

        if authorization:
            token = authorization.strip()
            while token.lower().startswith("bearer "):
                token = token[7:].strip()
        # Note: Query parameter token authentication removed for security.
        # SSE clients must use Authorization header or cookie-based authentication.

        if token:
            logger.error(
                "[AUTH_MIDDLEWARE] Authorization header found. Token starts with: {token[:15]}...",
                token15=token[:15],
            )

            # Chain of Responsibility / Strategy Execution
            strategy_found = False
            for strategy in self.strategies:
                logger.error(
                    "[AUTH_MIDDLEWARE] Evaluating strategy: {type(strategy).__name__}",
                    val_0=type(strategy).__name__,
                )
                if strategy.can_handle(token):
                    logger.error(
                        "[AUTH_MIDDLEWARE] Strategy {type(strategy).__name__} claimed the token!",
                        val_0=type(strategy).__name__,
                    )
                    strategy_found = True
                    try:
                        identity = await strategy.authenticate(token)
                        request.state.identity = identity
                        request.scope["identity"] = identity
                        break
                    except AuthenticationError:
                        # Don't reject here — let route-specific guards raise 401/403.
                        logger.debug(
                            "Bearer token present but failed validation at middleware layer "
                            "for path=%s — downstream guards will enforce.",
                            request.url.path,
                        )
                        request.state.identity = None
                        request.scope["identity"] = None
                        break
                    except TenantNotProvisionedError as e:
                        logger.warning(
                            "[AUTH_MIDDLEWARE] Tenant not provisioned: {e.tenant_id}",
                            e_tenant_id=e.tenant_id,
                        )
                        return JSONResponse(status_code=403, content={"detail": str(e)})

            if not strategy_found:
                logger.warning(
                    "[AUTH_MIDDLEWARE] No authentication strategy could handle the provided token."
                )
                request.state.identity = None
                request.scope["identity"] = None
        else:
            logger.warning("[AUTH_MIDDLEWARE] NO Authorization header found on request.")
            request.state.identity = None
            request.scope["identity"] = None

        logger.error(
            "[AUTH_MIDDLEWARE] Proceeding to call_next for {request.url.path} with identity={getattr(request.state, 'identity', None)}",
            request_url_path=request.url.path,
            val_1=getattr(request.state, "identity", None),
        )
        return await call_next(request)
