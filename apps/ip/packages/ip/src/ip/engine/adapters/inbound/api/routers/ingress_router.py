"""Inbound HTTP router for Integration Platform Ingestion Gateway (L1)."""

from __future__ import annotations

import json
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
from ip.engine.adapters.inbound.api.dependencies import (
    get_ingest_connection_webhook_use_case,
    resolve_tenant_id_by_slug,
)
from ip.engine.adapters.inbound.api.dtos.error_dtos import (
    ApiErrorHttpResponse,
    from_ip_error,
)
from ip.engine.adapters.inbound.api.dtos.ingress_dtos import IngressRecordHttpResponse
from ip.engine.application.use_cases.ingestion.ingest_connection_webhook_use_case import (
    IngestConnectionWebhookCommand,
    IngestConnectionWebhookUseCase,
)
from ip.engine.domain.constants import DEFAULT_WEBHOOK_STREAM
from seedwork.domain.types import JsonValue

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/webhooks",
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
    "/{tenant_slug}/{app_id}/{connection_id}",
    response_model=IngressRecordHttpResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
        status.HTTP_409_CONFLICT: {"model": ApiErrorHttpResponse},
    },
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_record(
    tenant_slug: str,
    app_id: str,
    connection_id: str,
    request: Request,
    tenant_id: Annotated[str, Depends(resolve_tenant_id_by_slug)],
    use_case: Annotated[
        IngestConnectionWebhookUseCase, Depends(get_ingest_connection_webhook_use_case)
    ],
    body: Annotated[dict[str, JsonValue] | list[JsonValue], Body(...)],
    stream_name: Annotated[
        str,
        Query(
            alias="stream",
            min_length=1,
            description="Target stream name; defaults to 'events' when omitted.",
        ),
    ] = DEFAULT_WEBHOOK_STREAM,
    correlation_id: Annotated[str | None, Header(alias="X-Correlation-ID")] = None,
) -> IngressRecordHttpResponse | Response:
    """Captures external raw data payloads with sub-20ms response and enqueues transactional outbox event."""
    _ = body
    log = logger.bind(
        tenant_slug=tenant_slug,
        tenant_id=tenant_id,
        app_id=app_id,
        connection_id=connection_id,
        stream_name=stream_name,
        correlation_id=correlation_id,
    )
    log.info("ip_ingest_record.received")

    safe_headers: dict[str, JsonValue] = {
        k: v for k, v in request.headers.items() if _is_allowed_ingress_header(k)
    }
    raw_payload = await request.body()
    external_event_id = (
        request.headers.get("X-Idempotency-Key")
        or request.headers.get("Idempotency-Key")
        or request.headers.get("X-External-Event-ID")
    )

    outcome = await use_case.execute(
        IngestConnectionWebhookCommand(
            tenant_id=tenant_id,
            app_id=app_id,
            connection_id=connection_id,
            stream_name=stream_name,
            raw_payload=raw_payload,
            headers=safe_headers,
            external_event_id=external_event_id,
            correlation_id=correlation_id,
        )
    )
    if outcome.is_err:
        err = outcome.unwrap_err()
        log.error("ip_ingest_record.failed", error_code=err.code.value)
        return from_ip_error(err)

    result = outcome.unwrap()
    if result.status_code >= 400:
        log.error(
            "ip_ingest_record.rejected",
            status_code=result.status_code,
            trace_id=result.trace_id,
            record_id=result.record_id,
        )
        content_body: str | bytes
        if isinstance(result.body, (str, bytes)):
            content_body = result.body
        else:
            content_body = json.dumps(result.body)
        media_type = "application/json" if isinstance(result.body, (dict, list)) else "text/plain"
        return Response(
            content=content_body,
            status_code=result.status_code,
            headers=dict(result.headers),
            media_type=media_type,
        )

    log.info(
        "ip_ingest_record.completed",
        record_id=result.record_id,
        trace_id=result.trace_id,
        payload_size_bytes=result.payload_size_bytes,
        is_inlined=result.is_inlined,
    )
    return IngressRecordHttpResponse(
        record_id=result.record_id or "",
        batch_id=result.batch_id,
        range_start=result.range_start,
        range_end=result.range_end,
        count=result.count,
        trace_id=result.trace_id,
        status="ACCEPTED",
        payload_size_bytes=result.payload_size_bytes,
        is_inlined=result.is_inlined,
    )
