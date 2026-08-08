"""
Bootstrap Middleware Package.

Each module in this package contains a single, focused middleware concern.
This package exposes ``setup_middleware(app)`` as the single integration
point for ``module.py`` — following the same convention as all other bootstrap
modules (``setup_exception_handlers``, etc.).

Current middleware stack (in registration order, outermost to innermost):
  1. Authentication — validates the JWT at the domain perimeter.

NOTE: CORS is intentionally NOT registered here. In a Modular Monolith with
Starlette/FastAPI sub-apps, CORS middleware on a sub-application is invisible
to the browser because preflight OPTIONS requests are intercepted and handled
by the outermost (Shell) application before being dispatched to sub-apps.
CORS must live exclusively on the Shell host (unified_api/main.py).
"""

from fastapi import FastAPI

from ucp.adapters.inbound.http.middleware.authentication import (
    _PUBLIC_PATHS,
    AuthenticationMiddleware,
)
from ucp.application.services.authenticators.api_key_strategy import ApiKeyStrategy
from ucp.application.services.authenticators.jwt_strategy import JwtStrategy
from ucp.core.container import _async_session_maker, get_token_verifier


def setup_middleware(app: FastAPI) -> None:
    """
    Registers all cross-cutting HTTP middleware on the UCP domain sub-application.
    """
    strategies = [
        ApiKeyStrategy(session_maker=_async_session_maker),
        JwtStrategy(session_maker=_async_session_maker, token_verifier=get_token_verifier()),
    ]
    app.add_middleware(
        AuthenticationMiddleware,
        strategies=strategies,
        public_paths=_PUBLIC_PATHS,
    )
