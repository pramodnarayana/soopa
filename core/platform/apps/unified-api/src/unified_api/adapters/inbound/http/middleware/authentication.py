"""
Global Authentication Middleware.

Validates the Bearer token exactly ONCE at the perimeter for every inbound
request. Attaches both ``IdentityContext`` (``request.state.identity``) and
immutable ``PrincipalContext`` (``request.state.principal``) so all downstream
guards (`RequireAuthorization`, `RequireCapability`, domain dependencies) read
from a single verified request state.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from identity.application.authenticate_use_case import (
    AuthenticationError,
    TenantNotProvisionedError,
)
from identity.domain.authentication_strategy import AuthenticationStrategyPort
from identity.domain.constants import MFA_AMR_VALUES, ActorType
from identity.domain.dtos import PrincipalContext
from identity.domain.identity_context import IdentityContext
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
        "/api/v1/auth/hrd",
    }
)


# Route prefixes authenticated by dedicated internal service-to-service guards (e.g. Dynamic Watch).
_INTERNAL_AUTH_PREFIXES: tuple[str, ...] = ("/api/v1/internal/",)


def _to_principal_context(identity: IdentityContext) -> PrincipalContext:
    """Translate verified `IdentityContext` into immutable `PrincipalContext` for the 4-Layer PDP."""
    claims = identity.claims
    iss_raw = claims.get("iss")
    idp_issuer = iss_raw.strip().rstrip("/") if isinstance(iss_raw, str) else ""
    sub_raw = claims.get("sub")
    idp_subject = str(sub_raw) if isinstance(sub_raw, str) and sub_raw else identity.subject

    iat_raw = claims.get("iat")
    token_issued_at = (
        datetime.fromtimestamp(iat_raw, tz=UTC) if isinstance(iat_raw, int) else datetime.now(UTC)
    )

    raw_amr = claims.get("amr")
    amr_values = (
        {str(item).lower() for item in raw_amr}
        if isinstance(raw_amr, (list, tuple, set))
        else set()
    )
    mfa_verified = bool(amr_values & MFA_AMR_VALUES)

    email_raw = claims.get("email")
    email = email_raw.strip().lower() if isinstance(email_raw, str) and email_raw.strip() else None
    email_verified = bool(claims.get("email_verified") or claims.get("emailVerified"))

    realm_raw = claims.get("owner") or claims.get("idp_realm")
    idp_realm = realm_raw.strip() if isinstance(realm_raw, str) and realm_raw.strip() else None

    jti_raw = claims.get("jti")
    jti = jti_raw if isinstance(jti_raw, str) and jti_raw else None

    is_machine = bool(claims.get("is_m2m")) or (not idp_issuer and identity.tenant_id is not None)
    actor_type = ActorType.MACHINE if is_machine else ActorType.HUMAN

    token_scopes: frozenset[str] | None = None
    if is_machine:
        combined_scopes: set[str] = set(identity.capabilities) | set(identity.permissions)
        raw_scopes = claims.get("scopes")
        if isinstance(raw_scopes, (list, tuple, set)):
            combined_scopes.update(
                scope.strip() for scope in raw_scopes if isinstance(scope, str) and scope.strip()
            )
        raw_scope = claims.get("scope")
        if isinstance(raw_scope, str) and raw_scope.strip():
            combined_scopes.update(raw_scope.split())
        token_scopes = frozenset(combined_scopes) if combined_scopes else None

    return PrincipalContext(
        user_id=identity.subject,
        idp_issuer=idp_issuer,
        idp_subject=idp_subject,
        actor_type=actor_type,
        token_issued_at=token_issued_at,
        assurance_level="aal2" if mfa_verified else "aal1",
        mfa_verified=mfa_verified,
        email=email,
        email_verified=email_verified,
        idp_realm=idp_realm,
        bound_tenant_id=identity.tenant_id if is_machine else None,
        token_scopes=token_scopes,
        jti=jti,
    )


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """
    ASGI middleware: validates the auth token once per request and populates
    ``request.state.identity`` / ``request.state.principal`` and ASGI scope keys.
    """

    def __init__(
        self,
        app: ASGIApp,
        strategies: Sequence[AuthenticationStrategyPort],
        public_paths: frozenset[str],
    ) -> None:
        super().__init__(app)
        self.strategies = strategies
        self.public_paths = public_paths

    @staticmethod
    def _preserve_bearer_challenge(
        response: Response, identity: IdentityContext | None
    ) -> Response:
        if identity is None:
            response.headers.setdefault("WWW-Authenticate", "Bearer")
        return response

    @staticmethod
    def _set_request_identity(request: Request, identity: IdentityContext | None) -> None:
        principal = _to_principal_context(identity) if identity is not None else None
        request.state.identity = identity
        request.state.principal = principal
        request.scope["identity"] = identity
        request.scope["principal"] = principal

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        self._set_request_identity(request, None)

        logger.debug(
            "auth_middleware_intercepted_request",
            path=request.url.path,
        )

        if request.url.path in self.public_paths or request.url.path.startswith(
            _INTERNAL_AUTH_PREFIXES
        ):
            return await call_next(request)

        authorization = request.headers.get("Authorization")
        token = ""

        if authorization:
            token = authorization.strip()
            while token.lower().startswith("bearer "):
                token = token[7:].strip()

        if token:
            logger.debug("auth_middleware_token_found", token_prefix=token[:15])
            strategy_found = False
            for strategy in self.strategies:
                if strategy.can_handle(token):
                    strategy_found = True
                    try:
                        identity = await strategy.authenticate(token)
                        self._set_request_identity(request, identity)
                        break
                    except AuthenticationError:
                        logger.debug(
                            "auth_middleware_authentication_failed",
                            path=request.url.path,
                        )
                        self._set_request_identity(request, None)
                        break
                    except TenantNotProvisionedError as e:
                        logger.error(
                            "auth_middleware_tenant_not_provisioned",
                            tenant_id=e.tenant_id,
                        )
                        return JSONResponse(status_code=403, content={"detail": str(e)})

            if not strategy_found:
                logger.error("auth_middleware_no_strategy_found", path=request.url.path)
        else:
            logger.debug("auth_middleware_no_authorization_header", path=request.url.path)

        response = await call_next(request)
        return self._preserve_bearer_challenge(response, request.state.identity)
