"""Shared request-state extractors for Unified API HTTP authorization guards."""

from __future__ import annotations

from database.provider import DatabaseProvider
from fastapi import Request
from identity.domain.dtos import PrincipalContext
from identity.domain.identity_context import IdentityContext

from unified_api.bootstrap.identity_authz import IdentityAuthzRuntime


def resolve_identity(request: Request) -> IdentityContext | None:
    """Return the verified `IdentityContext` attached by perimeter auth middleware."""
    try:
        identity: IdentityContext | None = request.state.identity
    except AttributeError:
        identity = None
    if identity is not None:
        return identity
    scoped_identity = request.scope.get("identity")
    return scoped_identity if isinstance(scoped_identity, IdentityContext) else None


def resolve_principal(request: Request) -> PrincipalContext | None:
    """Return the immutable `PrincipalContext` attached by perimeter auth middleware."""
    try:
        principal: object = request.state.principal
    except AttributeError:
        principal = None
    if isinstance(principal, PrincipalContext):
        return principal
    scoped_principal = request.scope.get("principal")
    return scoped_principal if isinstance(scoped_principal, PrincipalContext) else None


def resolve_runtime_and_db(
    request: Request,
) -> tuple[IdentityAuthzRuntime | None, DatabaseProvider | None]:
    """Return `(identity_authz, db_provider)` attached to the host FastAPI `app.state`."""
    try:
        app = request.app
    except KeyError:
        return None, None
    try:
        authz_runtime: IdentityAuthzRuntime | None = app.state.identity_authz
    except AttributeError:
        authz_runtime = None
    try:
        db_provider: DatabaseProvider | None = app.state.db_provider
    except AttributeError:
        db_provider = None
    return authz_runtime, db_provider


__all__ = [
    "resolve_identity",
    "resolve_principal",
    "resolve_runtime_and_db",
]
