"""OutboundRecord traced aggregate root for Layer 5 Outbound Gateway perimeter ledger."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from seedwork.domain.types import JsonDict
from seedwork.id_registry import DomainIdPrefix
from seedwork.models import TracedAggregateRoot
from seedwork.utils import generate_id

from ip.engine.domain.enums import (
    IpTraceEventType,
    OutboundDispatchStatus,
    PipelineLayer,
    TimelineStatus,
)
from ip.engine.domain.events import OutboundRecordCreatedEvent
from ip.engine.domain.models.timeline_entry import IpTraceEvent


def compute_request_sha256(payload_bytes: bytes) -> str:
    """Computes a SHA-256 hash for outgoing payload auditing."""
    return hashlib.sha256(payload_bytes).hexdigest()


@dataclass(kw_only=True, eq=False)
class OutboundRecord(TracedAggregateRoot):
    """Traced Aggregate Root representing an external outbound dispatch in the Outbound Gateway."""

    ID_PREFIX: ClassVar[str] = DomainIdPrefix.IP_OUTBOUND_RECORD.value

    id: str
    connection_id: str
    app_id: str
    stream_name: str
    target_url: str
    http_method: str
    request_headers: JsonDict = field(default_factory=dict)
    request_body: JsonDict | None = None
    request_s3_key: str | None = None
    request_size_bytes: int
    request_sha256: str
    status: OutboundDispatchStatus = OutboundDispatchStatus.PENDING
    response_status_code: int | None = None
    response_headers: JsonDict | None = None
    response_body: JsonDict | None = None
    response_s3_key: str | None = None
    duration_ms: int | None = None
    attempt_number: int = 1
    error_message: str | None = None
    sent_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create_pending(
        cls,
        *,
        tenant_id: str,
        connection_id: str,
        app_id: str,
        stream_name: str,
        target_url: str,
        http_method: str,
        payload_bytes: bytes,
        is_inlined: bool,
        trace_id: str,
        correlation_id: str | None = None,
        parent_trace_id: str | None = None,
        original_trace_id: str | None = None,
        replay_count: int = 0,
        request_headers: JsonDict | None = None,
        request_body: JsonDict | None = None,
        request_s3_key: str | None = None,
        status: OutboundDispatchStatus = OutboundDispatchStatus.PENDING,
    ) -> OutboundRecord:
        record_id = generate_id(cls.ID_PREFIX)
        size_bytes = len(payload_bytes)
        sha256_hash = compute_request_sha256(payload_bytes)

        record = cls(
            id=record_id,
            tenant_id=tenant_id,
            trace_id=trace_id,
            correlation_id=correlation_id,
            parent_trace_id=parent_trace_id,
            original_trace_id=original_trace_id,
            replay_count=replay_count,
            connection_id=connection_id,
            app_id=app_id,
            stream_name=stream_name,
            target_url=target_url,
            http_method=http_method,
            request_headers=dict(request_headers or {}),
            request_body=request_body if is_inlined else None,
            request_s3_key=request_s3_key if not is_inlined else None,
            request_size_bytes=size_bytes,
            request_sha256=sha256_hash,
            status=status,
            sent_at=datetime.now(UTC),
        )

        record.add_trace_event(
            IpTraceEvent.create(
                tenant_id=tenant_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                event_type=IpTraceEventType.L5_DISPATCH_PENDING.value,
                layer=PipelineLayer.L5_DELIVER,
                status=TimelineStatus.SUCCESS,
                summary_message=f"Staged L5 outbound dispatch to {http_method} {target_url}.",
            )
        )

        record.add_domain_event(
            OutboundRecordCreatedEvent(
                record_id=record_id,
                tenant_id=tenant_id,
                connection_id=connection_id,
                app_id=app_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                parent_trace_id=parent_trace_id,
                original_trace_id=original_trace_id,
                replay_count=replay_count,
                stream_name=stream_name,
                status=str(status),
                response_status_code=None,
            )
        )
        return record

    def mark_delivered(
        self,
        *,
        response_status_code: int,
        response_headers: JsonDict | None = None,
        response_body: JsonDict | None = None,
        response_s3_key: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Transitions state to DELIVERED upon successful response from destination."""
        self.status = OutboundDispatchStatus.DELIVERED
        self.response_status_code = response_status_code
        self.response_headers = response_headers
        self.response_body = response_body
        self.response_s3_key = response_s3_key
        self.duration_ms = duration_ms
        self.error_message = None
        self.add_trace_event(
            IpTraceEvent.create(
                tenant_id=self.tenant_id,
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
                event_type=IpTraceEventType.L5_DISPATCH_DELIVERED.value,
                layer=PipelineLayer.L5_DELIVER,
                status=TimelineStatus.SUCCESS,
                summary_message=f"Outbound dispatch delivered (HTTP {response_status_code}).",
            )
        )

    def mark_failed(
        self,
        *,
        error_message: str,
        response_status_code: int | None = None,
        response_headers: JsonDict | None = None,
        response_body: JsonDict | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Transitions state to FAILED upon unrecoverable error."""
        self.status = OutboundDispatchStatus.FAILED
        self.error_message = error_message
        self.response_status_code = response_status_code
        self.response_headers = response_headers
        self.response_body = response_body
        self.duration_ms = duration_ms
        self.add_trace_event(
            IpTraceEvent.create(
                tenant_id=self.tenant_id,
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
                event_type=IpTraceEventType.L5_DISPATCH_FAILED.value,
                layer=PipelineLayer.L5_DELIVER,
                status=TimelineStatus.FAILED,
                summary_message=error_message,
                error_details={"response_status_code": response_status_code},
            )
        )

    def schedule_retry(
        self,
        *,
        error_message: str,
        next_attempt: int,
        response_status_code: int | None = None,
    ) -> None:
        """Transitions state to RETRY_SCHEDULED for transient failures."""
        self.status = OutboundDispatchStatus.RETRY_SCHEDULED
        self.error_message = error_message
        self.attempt_number = next_attempt
        self.response_status_code = response_status_code
        self.add_trace_event(
            IpTraceEvent.create(
                tenant_id=self.tenant_id,
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
                event_type=IpTraceEventType.L5_DISPATCH_RETRY_SCHEDULED.value,
                layer=PipelineLayer.L5_DELIVER,
                status=TimelineStatus.RETRIED,
                summary_message=f"Scheduled retry #{next_attempt}: {error_message}",
                error_details={
                    "next_attempt": next_attempt,
                    "response_status_code": response_status_code,
                },
            )
        )
