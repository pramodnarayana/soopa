"""OutboundRecord traced aggregate root for Layer 5 Outbound Gateway perimeter ledger."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from seedwork.domain.types import JsonDict
from seedwork.id_registry import DomainIdPrefix
from seedwork.utils import generate_id
from strace.domain import TracedAggregateRoot

from ip.engine.domain.enums import (
    HttpWriteOperation,
    IpTraceEventType,
    OutboundDispatchStatus,
    PipelineLayer,
    TimelineStatus,
)
from ip.engine.domain.events import OutboundRecordCreatedEvent
from ip.engine.domain.models.timeline_entry import (
    IpTraceEvent,
    TraceErrorDetails,
    TraceReplayMetadata,
)
from ip.engine.domain.services.outbound_error_classifier import redact_sensitive_headers


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
    operation: str = HttpWriteOperation.CREATE.value
    idempotency_key: str | None = None
    external_record_id: str | None = None
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
    failure_category: str | None = None
    retry_after_seconds: int | None = None
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
        operation: str = HttpWriteOperation.CREATE.value,
        idempotency_key: str | None = None,
        external_record_id: str | None = None,
        correlation_id: str | None = None,
        parent_trace_id: str | None = None,
        original_trace_id: str | None = None,
        replay_count: int = 0,
        request_headers: JsonDict | None = None,
        request_body: JsonDict | None = None,
        request_s3_key: str | None = None,
        attempt_number: int = 1,
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
            operation=operation,
            idempotency_key=idempotency_key,
            external_record_id=external_record_id,
            target_url=target_url,
            http_method=http_method,
            request_headers=redact_sensitive_headers(request_headers),
            request_body=request_body if is_inlined else None,
            request_s3_key=request_s3_key if not is_inlined else None,
            request_size_bytes=size_bytes,
            request_sha256=sha256_hash,
            attempt_number=attempt_number,
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

    def update_wire_target(
        self,
        *,
        target_url: str,
        http_method: str,
        request_headers: JsonDict | None = None,
    ) -> None:
        """Updates wire-level request metadata resolved by the destination connector."""
        if target_url:
            self.target_url = target_url
        if http_method:
            self.http_method = http_method
        if request_headers is not None:
            self.request_headers = redact_sensitive_headers(request_headers)

    def mark_in_flight_attempt(
        self,
        *,
        attempt_number: int,
    ) -> None:
        """Marks an existing retryable OutboundRecord as PENDING in-flight prior to wire dispatch."""
        self.status = OutboundDispatchStatus.PENDING
        self.attempt_number = max(attempt_number, self.attempt_number)

    def mark_delivered(
        self,
        *,
        response_status_code: int,
        response_headers: JsonDict | None = None,
        response_body: JsonDict | None = None,
        response_s3_key: str | None = None,
        duration_ms: int | None = None,
        external_record_id: str | None = None,
    ) -> None:
        """Transitions state to DELIVERED upon successful response from destination."""
        self.status = OutboundDispatchStatus.DELIVERED
        self.response_status_code = response_status_code
        self.response_headers = (
            redact_sensitive_headers(response_headers) if response_headers is not None else None
        )
        self.response_body = response_body
        self.response_s3_key = response_s3_key
        self.duration_ms = duration_ms
        if external_record_id is not None:
            self.external_record_id = external_record_id
        self.failure_category = None
        self.retry_after_seconds = None
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
        response_s3_key: str | None = None,
        duration_ms: int | None = None,
        failure_category: str | None = None,
    ) -> None:
        """Transitions state to FAILED upon unrecoverable error."""
        self.status = OutboundDispatchStatus.FAILED
        self.error_message = error_message
        self.response_status_code = response_status_code
        self.response_headers = (
            redact_sensitive_headers(response_headers) if response_headers is not None else None
        )
        self.response_body = response_body
        self.response_s3_key = response_s3_key
        self.duration_ms = duration_ms
        self.failure_category = failure_category
        self.retry_after_seconds = None
        self.add_trace_event(
            IpTraceEvent.create(
                tenant_id=self.tenant_id,
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
                event_type=IpTraceEventType.L5_DISPATCH_FAILED.value,
                layer=PipelineLayer.L5_DELIVER,
                status=TimelineStatus.FAILED,
                summary_message=error_message,
                error_details=TraceErrorDetails(
                    response_status_code=response_status_code,
                    failure_category=failure_category,
                ),
            )
        )

    def schedule_retry(
        self,
        *,
        error_message: str,
        next_attempt: int,
        response_status_code: int | None = None,
        response_headers: JsonDict | None = None,
        response_body: JsonDict | None = None,
        response_s3_key: str | None = None,
        duration_ms: int | None = None,
        failure_category: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        """Transitions state to RETRY_SCHEDULED for transient or rate-limited failures."""
        self.status = OutboundDispatchStatus.RETRY_SCHEDULED
        self.error_message = error_message
        self.attempt_number = next_attempt
        self.response_status_code = response_status_code
        if response_headers is not None:
            self.response_headers = redact_sensitive_headers(response_headers)
        if response_body is not None:
            self.response_body = response_body
        if response_s3_key is not None:
            self.response_s3_key = response_s3_key
        if duration_ms is not None:
            self.duration_ms = duration_ms
        self.failure_category = failure_category
        self.retry_after_seconds = retry_after_seconds
        self.add_trace_event(
            IpTraceEvent.create(
                tenant_id=self.tenant_id,
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
                event_type=IpTraceEventType.L5_DISPATCH_RETRY_SCHEDULED.value,
                layer=PipelineLayer.L5_DELIVER,
                status=TimelineStatus.RETRIED,
                summary_message=f"Scheduled retry #{next_attempt}: {error_message}",
                error_details=TraceErrorDetails(
                    next_attempt=next_attempt,
                    response_status_code=response_status_code,
                    failure_category=failure_category,
                    retry_after_seconds=retry_after_seconds,
                ),
            )
        )

    def clone_for_delivery_retry(
        self,
        *,
        new_id: str | None = None,
        new_trace_id: str | None = None,
        parent_trace_id: str | None = None,
        original_trace_id: str | None = None,
        replay_count: int | None = None,
        actor: str = "SYSTEM",
    ) -> OutboundRecord:
        """Clones the OutboundRecord as a fresh PENDING delivery attempt under a new replay trace."""
        resolved_id = new_id or generate_id(self.ID_PREFIX)
        resolved_trace_id = new_trace_id or generate_id(DomainIdPrefix.IP_TRACE.value)
        resolved_parent_id = parent_trace_id or self.trace_id
        root_trace_id = original_trace_id or self.original_trace_id or self.trace_id
        next_replay_count = replay_count if replay_count is not None else self.replay_count + 1
        fresh_idempotency_key = f"{resolved_trace_id}:{self.stream_name}:{self.operation}"

        cloned = OutboundRecord(
            id=resolved_id,
            tenant_id=self.tenant_id,
            trace_id=resolved_trace_id,
            correlation_id=self.correlation_id,
            parent_trace_id=resolved_parent_id,
            original_trace_id=root_trace_id,
            replay_count=next_replay_count,
            connection_id=self.connection_id,
            app_id=self.app_id,
            stream_name=self.stream_name,
            operation=self.operation,
            idempotency_key=fresh_idempotency_key,
            external_record_id=self.external_record_id,
            target_url=self.target_url,
            http_method=self.http_method,
            request_headers=redact_sensitive_headers(self.request_headers),
            request_body=dict(self.request_body) if self.request_body is not None else None,
            request_s3_key=self.request_s3_key,
            request_size_bytes=self.request_size_bytes,
            request_sha256=self.request_sha256,
            attempt_number=1,
            status=OutboundDispatchStatus.PENDING,
            sent_at=datetime.now(UTC),
        )
        cloned.add_trace_event(
            IpTraceEvent.create(
                tenant_id=self.tenant_id,
                trace_id=resolved_trace_id,
                correlation_id=self.correlation_id,
                event_type=IpTraceEventType.REPLAY_TRIGGERED.value,
                actor=actor,
                layer=PipelineLayer.L5_DELIVER,
                status=TimelineStatus.RETRIED,
                summary_message=(
                    f"Replayed L5 outbound delivery to {self.http_method} {self.target_url} "
                    f"from '{resolved_parent_id}' (attempt #{next_replay_count})."
                ),
                replay_metadata=TraceReplayMetadata(
                    parent_trace_id=resolved_parent_id,
                    original_trace_id=root_trace_id,
                    replay_count=next_replay_count,
                ),
            )
        )
        cloned.add_domain_event(
            OutboundRecordCreatedEvent(
                record_id=resolved_id,
                tenant_id=self.tenant_id,
                connection_id=self.connection_id,
                app_id=self.app_id,
                trace_id=resolved_trace_id,
                correlation_id=self.correlation_id,
                parent_trace_id=resolved_parent_id,
                original_trace_id=root_trace_id,
                replay_count=next_replay_count,
                stream_name=self.stream_name,
                status=OutboundDispatchStatus.PENDING.value,
                response_status_code=None,
            )
        )
        return cloned
