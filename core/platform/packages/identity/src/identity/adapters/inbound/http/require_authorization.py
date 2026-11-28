"""Declarative FastAPI authorization guard backed by AuthorizationEnginePort."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog
from fastapi import HTTPException, Request, status

from identity.domain.constants import AuthzReasonCode
from identity.domain.dtos import AuthzDecision, AuthzRequest, PrincipalContext, ResourceContext
from identity.ports.outbound.authorization_engine_port import AuthorizationEnginePort

logger = structlog.get_logger(__name__)

ResourceResolver = Callable[[Request], Awaitable[ResourceContext | None]]
TenantResolver = Callable[[Request], str | None]


def _default_tenant_resolver(request: Request) -> str | None:
    path_tid = request.path_params.get("tenant_id")
    if isinstance(path_tid, str) and path_tid.strip():
        return path_tid.strip()
    header_tid = request.headers.get("x-tenant-id")
    if header_tid and header_tid.strip():
        return header_tid.strip()
    return None


def http_status_for_authz_reason(reason: AuthzReasonCode) -> int:
    if reason in (
        AuthzReasonCode.DENIED_UNAUTHENTICATED,
        AuthzReasonCode.DENIED_UNTRUSTED_ISSUER,
        AuthzReasonCode.DENIED_TOKEN_REVOKED,
    ):
        return status.HTTP_401_UNAUTHORIZED
    return status.HTTP_403_FORBIDDEN


_http_status_for_reason = http_status_for_authz_reason


class RequireAuthorization:
    """FastAPI dependency delegating authorization to the injected AuthorizationEnginePort."""

    def __init__(
        self,
        *,
        app_slug: str,
        action: str,
        engine_getter: Callable[[Request], AuthorizationEnginePort],
        tenant_resolver: TenantResolver | None = None,
        resource_resolver: ResourceResolver | None = None,
    ) -> None:
        self._app_slug = app_slug
        self._action = action
        self._engine_getter = engine_getter
        self._tenant_resolver = tenant_resolver or _default_tenant_resolver
        self._resource_resolver = resource_resolver

    async def __call__(self, request: Request) -> PrincipalContext:
        try:
            raw_principal: object = request.state.principal
        except AttributeError:
            raw_principal = None
        if not isinstance(raw_principal, PrincipalContext):
            logger.error("authz.guard.missing_principal", path=request.url.path)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": AuthzReasonCode.DENIED_UNAUTHENTICATED.value},
                headers={"WWW-Authenticate": "Bearer"},
            )

        tenant_id = self._tenant_resolver(request)
        if not tenant_id:
            logger.error(
                "authz.guard.missing_tenant_id",
                path=request.url.path,
                user_id=raw_principal.user_id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": AuthzReasonCode.DENIED_TENANT_NOT_FOUND.value},
            )

        resource = (
            await self._resource_resolver(request) if self._resource_resolver is not None else None
        )
        client_ip = request.client.host if request.client is not None else None

        engine = self._engine_getter(request)
        decision: AuthzDecision = await engine.evaluate(
            AuthzRequest(
                principal=raw_principal,
                app_slug=self._app_slug,
                action=self._action,
                tenant_id=tenant_id,
                resource=resource,
                client_ip=client_ip,
            )
        )
        if not decision.is_allowed:
            raise HTTPException(
                status_code=_http_status_for_reason(decision.reason_code),
                detail={
                    "code": decision.reason_code.value,
                    "obligations": [ob.value for ob in decision.obligations],
                },
            )
        return raw_principal


__all__ = [
    "RequireAuthorization",
    "ResourceResolver",
    "TenantResolver",
    "http_status_for_authz_reason",
]
