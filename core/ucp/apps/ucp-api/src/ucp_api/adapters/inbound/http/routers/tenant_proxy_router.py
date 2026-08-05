import logging
from collections.abc import AsyncGenerator
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.responses import StreamingResponse
from identity.domain.identity_context import IdentityContext

from ucp_api.adapters.inbound.http.guards.tenant_auth_guard import require_tenant_member
from ucp_api.core.config import get_settings
from ucp_api.ports.outbound.tenant_repository import ITenantRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants/{tenant_id}/edi", tags=["Tenant Proxy"])

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "transfer-encoding",
    "te",
    "trailer",
    "upgrade",
    "proxy-authorization",
    "proxy-authenticate",
    "host",
}


# Dependency placeholder — overridden in main.py via dependency_overrides
def get_tenant_repo() -> ITenantRepository:
    raise NotImplementedError()


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def proxy_to_edi(
    request: Request,
    _: Annotated[IdentityContext, Depends(require_tenant_member)],
    tenant_id: str = Path(...),
    path: str = Path(...),
) -> StreamingResponse:
    """
    Transparently proxies requests to the downstream EDI API.

    The ``require_tenant_member`` guard resolves and validates the tenant
    before reaching this handler. It writes the canonical UCP tenant ID to
    ``request.state.ucp_tenant_id``, which we inject as the ``x-tenant-id``
    header for the downstream service — avoiding a second DB round-trip.
    """
    # The guard has already resolved and validated the tenant; consume it from state.
    ucp_tenant_id: str = getattr(request.state, "ucp_tenant_id", tenant_id)

    settings = get_settings()
    edi_api_url = getattr(settings, "edi_api_url", None)
    if not edi_api_url or not edi_api_url.startswith("https://"):
        raise HTTPException(status_code=500, detail="Secure proxy target not configured.")

    target_url = f"{edi_api_url.rstrip('/')}/api/v1/{path}"
    query = request.url.query
    if query:
        target_url += f"?{query}"

    logger.info(
        "[PROXY] %s %s -> %s (tenant=%s)", request.method, request.url, target_url, ucp_tenant_id
    )

    forward_headers: dict[str, str] = {}
    for key, value in request.headers.items():
        key_lower = key.lower()
        if key_lower not in HOP_BY_HOP_HEADERS and key_lower not in ("authorization", "cookie"):
            forward_headers[key] = value

    # Inject the resolved canonical tenant ID for the downstream EDI API.
    forward_headers["x-tenant-id"] = ucp_tenant_id

    # Stream the request body directly instead of buffering
    client = httpx.AsyncClient()
    try:
        req = client.build_request(
            method=request.method,
            url=target_url,
            headers=forward_headers,
            content=request.stream(),
        )
        response = await client.send(req, stream=True)
    except httpx.RequestError as exc:
        await client.aclose()
        logger.exception("[PROXY ERROR] Failed to proxy to %s", target_url)
        raise HTTPException(
            status_code=502,
            detail="Failed to communicate with downstream EDI service.",
        ) from exc

    res_headers: dict[str, str] = {}
    for key, value in response.headers.items():
        if key.lower() not in HOP_BY_HOP_HEADERS:
            res_headers[key] = value

    # Stream the response back instead of buffering
    async def stream_response() -> AsyncGenerator[bytes, None]:
        try:
            async for chunk in response.aiter_raw():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return StreamingResponse(
        content=stream_response(),
        status_code=response.status_code,
        headers=res_headers,
    )
