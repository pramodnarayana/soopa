"""InboundRecord traced aggregate root for Layer 1 Inbound Gateway perimeter ledger."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from seedwork.domain.types import JsonDict
from seedwork.id_registry import DomainIdPrefix
from seedwork.models import TracedAggregateRoot
from seedwork.utils import generate_id

from ip.engine.domain.enums import IpTraceEventType, PipelineLayer, TimelineStatus
from ip.engine.domain.events import InboundRecordCreatedEvent
from ip.engine.domain.models.timeline_entry import IpTraceEvent


def compute_payload_sha256(payload_bytes: bytes) -> str:
    """Computes a SHA-256 hash for raw payload change detection."""
    return hashlib.sha256(payload_bytes).hexdigest()


@dataclass(kw_only=True, eq=False)
class InboundRecord(TracedAggregateRoot):
    """Traced Aggregate Root representing an immutable external raw record in Layer 1 Inbound Gateway."""

    ID_PREFIX: ClassVar[str] = DomainIdPrefix.IP_INBOUND_RECORD.value

    id: str
    connection_id: str
    app_id: str
    stream_name: str
    request_headers: JsonDict = field(default_factory=dict)
    request_body: JsonDict | None = None
    request_s3_key: str | None = None
    request_size_bytes: int
    request_sha256: str
    response_status_code: int | None = None
    response_headers: JsonDict | None = None
    response_body: JsonDict | None = None
    response_s3_key: str | None = None
    duration_ms: int | None = None
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        connection_id: str,
        app_id: str,
        stream_name: str,
        payload_bytes: bytes,
        is_inlined: bool,
        trace_id: str | None = None,
        correlation_id: str | None = None,
        parent_trace_id: str | None = None,
        original_trace_id: str | None = None,
        replay_count: int = 0,
        request_headers: JsonDict | None = None,
        request_body: JsonDict | None = None,
        request_s3_key: str | None = None,
        response_status_code: int | None = None,
        response_headers: JsonDict | None = None,
        response_body: JsonDict | None = None,
        response_s3_key: str | None = None,
        duration_ms: int | None = None,
    ) -> InboundRecord:
        record_id = generate_id(cls.ID_PREFIX)
        resolved_trace_id = trace_id or generate_id(DomainIdPrefix.IP_TRACE.value)
        size_bytes = len(payload_bytes)
        sha256_hash = compute_payload_sha256(payload_bytes)

        record = cls(
            id=record_id,
            tenant_id=tenant_id,
            trace_id=resolved_trace_id,
            correlation_id=correlation_id,
            parent_trace_id=parent_trace_id,
            original_trace_id=original_trace_id,
            replay_count=replay_count,
            connection_id=connection_id,
            app_id=app_id,
            stream_name=stream_name,
            request_headers=dict(request_headers or {}),
            request_body=request_body if is_inlined else None,
            request_s3_key=request_s3_key if not is_inlined else None,
            request_size_bytes=size_bytes,
            request_sha256=sha256_hash,
            response_status_code=response_status_code,
            response_headers=response_headers,
            response_body=response_body,
            response_s3_key=response_s3_key,
            duration_ms=duration_ms,
            received_at=datetime.now(UTC),
        )

        record.add_trace_event(
            IpTraceEvent.create(
                tenant_id=tenant_id,
                trace_id=resolved_trace_id,
                correlation_id=correlation_id,
                event_type=IpTraceEventType.L1_INGEST_RECEIVED.value,
                layer=PipelineLayer.L1_INGEST,
                status=TimelineStatus.SUCCESS,
                summary_message=f"Ingested inbound stream '{stream_name}' ({size_bytes} bytes).",
            )
        )

        record.add_domain_event(
            InboundRecordCreatedEvent(
                record_id=record_id,
                tenant_id=tenant_id,
                connection_id=connection_id,
                app_id=app_id,
                trace_id=resolved_trace_id,
                correlation_id=correlation_id,
                parent_trace_id=parent_trace_id,
                original_trace_id=original_trace_id,
                replay_count=replay_count,
                stream_name=stream_name,
                payload_size_bytes=size_bytes,
                payload_sha256=sha256_hash,
                is_inlined=is_inlined,
                s3_key=request_s3_key if not is_inlined else None,
            )
        )
        return record
