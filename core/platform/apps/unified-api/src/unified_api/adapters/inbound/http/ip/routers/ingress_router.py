"""Inbound HTTP router for Integration Platform Ingestion Gateway (L1)."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import (
    APIRouter,
    Body,
    Depends,
    Header,
    Query,
    Request,
    Response,
    status,
)
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.outbound.inbound.ack import StandardInboundAck
from ip.engine.adapters.outbound.inbound.decoders import StandardInboundPayloadDecoder
from ip.engine.adapters.outbound.inbound.verifiers import NoOpVerifier
from ip.engine.application.use_cases.connections.get_connection_use_case import (
    GetConnectionQuery,
    GetConnectionUseCase,
)
from ip.engine.application.use_cases.ingestion.receive_push_use_case import (
    ReceivePushCommand,
    ReceivePushUseCase,
)
from ip.engine.domain.enums import ConnectionStatus
from ip.engine.domain.exceptions import ConnectionDeactivatedError, ConnectionNotFoundError
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)
from seedwork.domain.types import JsonValue

from unified_api.adapters.inbound.http.dependencies.ip.database import (
    get_ip_control_plane_uow,
    get_ip_data_plane_uow_provider,
)
from unified_api.adapters.inbound.http.dependencies.ip.services import get_tiered_storage
from unified_api.adapters.inbound.http.guards.tenant_auth_guard import require_tenant_member
from unified_api.adapters.inbound.http.ip.dtos.error_dtos import (
    ApiErrorHttpResponse,
    from_ip_error,
)
from unified_api.adapters.inbound.http.ip.dtos.ingress_dtos import IngressRecordHttpResponse

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/ip/ingress",
    tags=["Integration Platform - Ingestion Gateway (L1)"],
)

ALLOWED_INGRESS_HEADER_NAMES = frozenset(
    {
        "content-type",
        "content-length",
        "user-agent",
        "host",
        "stripe-signature",
        "x-idempotency-key",
        "idempotency-key",
    }
)

SENSITIVE_HEADER_NAMES = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "proxy-authorization",
        "proxy-authenticate",
    }
)

SENSITIVE_HEADER_FRAGMENTS = frozenset(
    {
        "auth",
        "token",
        "secret",
        "password",
        "cookie",
        "credential",
        "session",
        "api-key",
        "apikey",
        "bearer",
    }
)


def _is_allowed_ingress_header(header_name: str) -> bool:
    normalized = header_name.strip().lower()
    if normalized in SENSITIVE_HEADER_NAMES:
        return False

    for frag in SENSITIVE_HEADER_FRAGMENTS:
        if frag in normalized:
            return False

    if "key" in normalized and "idempotency" not in normalized:
        return False

    if normalized in ALLOWED_INGRESS_HEADER_NAMES:
        return True

    if normalized.endswith(("-signature", "-hmac", "-signature-256")) or (
        "signature" in normalized or "hmac" in normalized
    ):
        return True

    return normalized.startswith("x-")


@router.post(
    "/{connection_id}",
    response_model=IngressRecordHttpResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
        status.HTTP_409_CONFLICT: {"model": ApiErrorHttpResponse},
    },
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_record(
    tenant_id: str,
    connection_id: str,
    request: Request,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    ip_cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
    ip_dp_uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    tiered_storage: Annotated[TieredStoragePort, Depends(get_tiered_storage)],
    stream_name: str = Query(
        ..., alias="stream", description="Target stream name, e.g. meters, contacts"
    ),
    body: dict[str, JsonValue] | list[JsonValue] = Body(...),
    correlation_id: str | None = Header(None, alias="X-Correlation-ID"),
) -> IngressRecordHttpResponse | Response:
    """Captures external raw data payloads with sub-20ms response and enqueues transactional outbox event."""
    get_conn_use_case = GetConnectionUseCase(uow=ip_cp_uow)
    conn_res = await get_conn_use_case.execute(
        GetConnectionQuery(tenant_id=tenant_id, connection_id=connection_id)
    )
    if not conn_res.success or conn_res.connection is None:
        return from_ip_error(conn_res.error or ConnectionNotFoundError.for_id(connection_id))

    conn = conn_res.connection
    if conn.status == ConnectionStatus.DEACTIVATED.value:
        return from_ip_error(ConnectionDeactivatedError.for_id(connection_id))

    safe_headers: dict[str, JsonValue] = {
        k: v for k, v in request.headers.items() if _is_allowed_ingress_header(k)
    }
    raw_payload = await request.body()
    external_event_id = (
        request.headers.get("X-Idempotency-Key")
        or request.headers.get("Idempotency-Key")
        or request.headers.get("X-External-Event-ID")
    )

    cmd = ReceivePushCommand(
        tenant_id=tenant_id,
        connection_id=connection_id,
        app_id=conn.app_id,
        stream_name=stream_name,
        raw_payload=raw_payload,
        headers=safe_headers,
        external_event_id=external_event_id,
        correlation_id=correlation_id,
    )

    shard_res = await ip_dp_uow_provider.resolve_shard_info(tenant_id)
    if shard_res.is_err or shard_res.value is None:
        assert shard_res.error is not None
        return from_ip_error(shard_res.error)

    shard_id, shard_dsn = shard_res.value
    async with ip_dp_uow_provider.get_data_plane_uow(
        tenant_id=tenant_id,
        shard_id=shard_id,
        shard_dsn=shard_dsn,
    ) as ip_dp_uow:
        use_case = ReceivePushUseCase(
            uow=ip_dp_uow,
            tiered_storage=tiered_storage,
            verifier=NoOpVerifier(),
            decoder=StandardInboundPayloadDecoder(),
            ack=StandardInboundAck(),
        )
        result = await use_case.execute(cmd)

    return IngressRecordHttpResponse(
        record_id=result.record_id or "",
        trace_id=result.trace_id,
        status="ACCEPTED",
        payload_size_bytes=result.payload_size_bytes,
        is_inlined=result.is_inlined,
    )
