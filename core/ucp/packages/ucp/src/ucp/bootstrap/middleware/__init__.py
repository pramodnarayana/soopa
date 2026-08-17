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

import contextlib
from collections.abc import AsyncGenerator

from fastapi import FastAPI

from ucp.adapters.inbound.http.middleware.authentication import (
    _PUBLIC_PATHS,
    AuthenticationMiddleware,
)
from ucp.adapters.outbound.database.postgres_api_token_repository import PostgresApiTokenRepository
from ucp.adapters.outbound.database.role_repository import PostgresRoleRepository
from ucp.adapters.outbound.database.tenant_repository import TenantRepository
from ucp.adapters.outbound.database.user_repository import UserRepository
from ucp.application.services.authenticators.api_key_strategy import ApiKeyStrategy
from ucp.application.services.authenticators.jwt_strategy import JwtStrategy
from ucp.core.container import _async_session_maker, get_token_verifier


def setup_middleware(app: FastAPI) -> None:
    """
    Registers all cross-cutting HTTP middleware on the UCP domain sub-application.
    """

    @contextlib.asynccontextmanager
    async def api_token_repo_factory() -> AsyncGenerator[PostgresApiTokenRepository, None]:
        async with _async_session_maker() as session:
            yield PostgresApiTokenRepository(session)

    @contextlib.asynccontextmanager
    async def tenant_repo_factory() -> AsyncGenerator[TenantRepository, None]:
        async with _async_session_maker() as session:
            yield TenantRepository(session)

    @contextlib.asynccontextmanager
    async def user_repo_factory() -> AsyncGenerator[UserRepository, None]:
        async with _async_session_maker() as session:
            yield UserRepository(session)

    @contextlib.asynccontextmanager
    async def role_repo_factory() -> AsyncGenerator[PostgresRoleRepository, None]:
        async with _async_session_maker() as session:
            yield PostgresRoleRepository(session)

    strategies = [
        ApiKeyStrategy(token_repo_factory=api_token_repo_factory),
        JwtStrategy(
            tenant_repo_factory=tenant_repo_factory,
            user_repo_factory=user_repo_factory,
            role_repo_factory=role_repo_factory,
            token_verifier=get_token_verifier(),
        ),
    ]
    app.add_middleware(
        AuthenticationMiddleware,
        strategies=strategies,
        public_paths=_PUBLIC_PATHS,
    )
