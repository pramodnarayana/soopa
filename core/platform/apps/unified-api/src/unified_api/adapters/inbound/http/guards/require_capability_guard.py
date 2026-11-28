"""Declarative FastAPI authorization guard backed by the 4-Layer Local PDP."""

from __future__ import annotations

import structlog
from database.provider import DatabaseProvider
from fastapi import HTTPException, Request, status
from identity.adapters.inbound.http.require_authorization import (
    ResourceResolver,
    http_status_for_authz_reason,
)
from identity.domain.authorization import Capability
from identity.domain.constants import AuthzReasonCode, CoreControlPlaneAppSlug
from identity.domain.dtos import AuthzDecision, AuthzRequest, PrincipalContext
from identity.domain.identity_context import PLATFORM_TENANT_ID, IdentityContext

from unified_api.adapters.inbound.http.guards.request_context import (
    resolve_identity,
    resolve_principal,
    resolve_runtime_and_db,
)
from unified_api.bootstrap.identity_authz import IdentityAuthzRuntime

logger = structlog.get_logger(__name__)


def _resolve_target_tenant_id(
    request: Request,
    identity: IdentityContext,
    required_capability: str,
) -> str | None:
    if required_capability == Capability.PLATFORM_ADMIN.value:
        return PLATFORM_TENANT_ID

    try:
        ucp_tid: object = request.state.ucp_tenant_id
    except AttributeError:
        ucp_tid = None
    if isinstance(ucp_tid, str) and ucp_tid.strip():
        return ucp_tid.strip()

    raw_path_tid = request.path_params.get("tenant_id")
    if isinstance(raw_path_tid, str) and raw_path_tid.strip():
        cleaned = raw_path_tid.strip()
        return str(identity.tenant_mapping.get(cleaned, cleaned))

    header_tid = request.headers.get("x-tenant-id")
    if header_tid and header_tid.strip():
        cleaned = header_tid.strip()
        return str(identity.tenant_mapping.get(cleaned, cleaned))

    try:
        state_tid: object = request.state.tenant_id
    except AttributeError:
        state_tid = None
    if isinstance(state_tid, str) and state_tid.strip():
        cleaned = state_tid.strip()
        return str(identity.tenant_mapping.get(cleaned, cleaned))

    if identity.tenant_id:
        return str(identity.tenant_mapping.get(identity.tenant_id, identity.tenant_id))

    if identity.is_platform_admin:
        return PLATFORM_TENANT_ID
    return None


def _raise_for_denied_decision(decision: AuthzDecision) -> None:
    status_code = http_status_for_authz_reason(decision.reason_code)
    headers = (
        {"WWW-Authenticate": "Bearer"} if status_code == status.HTTP_401_UNAUTHORIZED else None
    )
    raise HTTPException(
        status_code=status_code,
        detail={
            "code": decision.reason_code.value,
            "obligations": [ob.value for ob in decision.obligations],
        },
        headers=headers,
    )


class RequireCapability:
    """
    FastAPI dependency enforcing PBAC / ABAC / ReBAC / Hierarchical authorization
    through the 4-Layer Local PDP (`HybridLocalAuthorizationEngine` + L1 LRU cache).

    Usage:
        @router.get("/invoices", dependencies=[Depends(RequireCapability(Capability.INVOICES_READ))])
    """

    def __init__(
        self,
        required_capability: str,
        *,
        app_slug: str = CoreControlPlaneAppSlug.UCP.value,
        resource_resolver: ResourceResolver | None = None,
    ) -> None:
        self.required_capability = str(required_capability)
        self.app_slug = str(app_slug)
        self._resource_resolver = resource_resolver

    async def __call__(self, request: Request) -> IdentityContext:
        identity = resolve_identity(request)
        if identity is None:
            logger.error("authz.denied.unauthenticated", path=request.url.path)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )

        authz_runtime, db_provider = resolve_runtime_and_db(request)
        principal = resolve_principal(request)
        if authz_runtime is not None:
            if db_provider is None or principal is None:
                logger.error(
                    "authz.pdp.runtime_incomplete",
                    path=request.url.path,
                    required_capability=self.required_capability,
                    has_db_provider=db_provider is not None,
                    has_principal=principal is not None,
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "code": AuthzReasonCode.DENIED_UNAUTHENTICATED.value,
                        "obligations": [],
                    },
                )
            return await self._evaluate_via_local_pdp(
                request=request,
                identity=identity,
                principal=principal,
                authz_runtime=authz_runtime,
                db_provider=db_provider,
            )

        logger.debug(
            "authz.guard.standalone_fallback",
            path=request.url.path,
            required_capability=self.required_capability,
        )
        return self._evaluate_standalone_identity(request=request, identity=identity)

    async def _evaluate_via_local_pdp(
        self,
        *,
        request: Request,
        identity: IdentityContext,
        principal: PrincipalContext,
        authz_runtime: IdentityAuthzRuntime,
        db_provider: DatabaseProvider,
    ) -> IdentityContext:
        target_tenant_id = _resolve_target_tenant_id(request, identity, self.required_capability)
        if not target_tenant_id:
            logger.error(
                "authz.denied.missing_tenant_id",
                path=request.url.path,
                user_id=principal.user_id,
                required_capability=self.required_capability,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": AuthzReasonCode.DENIED_TENANT_NOT_FOUND.value, "obligations": []},
            )

        resource = (
            await self._resource_resolver(request) if self._resource_resolver is not None else None
        )
        client_ip = request.client.host if request.client is not None else None

        async with db_provider.session() as session:
            engine = authz_runtime.build_engine(session)
            decision = await engine.evaluate(
                AuthzRequest(
                    principal=principal,
                    app_slug=self.app_slug,
                    action=self.required_capability,
                    tenant_id=target_tenant_id,
                    resource=resource,
                    client_ip=client_ip,
                )
            )
            if (
                not decision.is_allowed
                and decision.reason_code == AuthzReasonCode.DENIED_TENANT_NOT_FOUND
                and self.required_capability != Capability.PLATFORM_ADMIN.value
            ):
                platform_decision = await engine.evaluate(
                    AuthzRequest(
                        principal=principal,
                        app_slug=CoreControlPlaneAppSlug.PLATFORM.value,
                        action=Capability.PLATFORM_ADMIN.value,
                        tenant_id=PLATFORM_TENANT_ID,
                        client_ip=client_ip,
                    )
                )
                if platform_decision.is_allowed:
                    return identity

        if not decision.is_allowed:
            _raise_for_denied_decision(decision)

        return identity

    def _evaluate_standalone_identity(
        self,
        *,
        request: Request,
        identity: IdentityContext,
    ) -> IdentityContext:
        if identity.is_platform_admin:
            return identity

        if (
            Capability.TENANT_ADMIN.value in identity.capabilities
            and self.required_capability != Capability.PLATFORM_ADMIN.value
        ):
            return identity

        if self.required_capability not in identity.capabilities:
            logger.error(
                "authz.denied.missing_capability",
                path=request.url.path,
                tenant_id=identity.tenant_id,
                user_id=identity.subject,
                required_capability=self.required_capability,
                actual_capabilities=sorted(identity.capabilities),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden. Missing required capability: {self.required_capability}",
            )

        return identity


__all__ = ["RequireCapability"]
