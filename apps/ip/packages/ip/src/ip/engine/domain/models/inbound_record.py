"""InboundRecord traced aggregate root for Layer 1 Inbound Gateway perimeter ledger."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from seedwork.domain.types import JsonDict
from seedwork.id_registry import DomainIdPrefix
from seedwork.utils import generate_id
from strace.domain import TracedAggregateRoot

from ip.engine.domain.enums import (
    IngestionMode,
    IpTraceEventType,
    PipelineLayer,
    TimelineStatus,
)
from ip.engine.domain.events import InboundRecordCreatedEvent
from ip.engine.domain.models.timeline_entry import IpTraceEvent, TraceReplayMetadata


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
    ingestion_mode: IngestionMode = IngestionMode.PUSH_FULL
    sync_run_id: str | None = None
    generation_id: int | None = None
    external_event_id: str | None = None
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
        ingestion_mode: IngestionMode = IngestionMode.PUSH_FULL,
        sync_run_id: str | None = None,
        generation_id: int | None = None,
        external_event_id: str | None = None,
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
            ingestion_mode=ingestion_mode,
            sync_run_id=sync_run_id,
            generation_id=generation_id,
            external_event_id=external_event_id,
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
                summary_message=f"Ingested inbound stream '{stream_name}' via {ingestion_mode.value} ({size_bytes} bytes).",
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
                ingestion_mode=ingestion_mode.value,
                sync_run_id=sync_run_id,
                generation_id=generation_id,
                external_event_id=external_event_id,
            )
        )
        return record

    def clone_for_replay(
        self,
        *,
        new_id: str | None = None,
        new_trace_id: str | None = None,
        parent_trace_id: str | None = None,
        original_trace_id: str | None = None,
        replay_count: int | None = None,
        modified_request_body: JsonDict | None = None,
        modified_payload_bytes: bytes | None = None,
        actor: str = "SYSTEM",
    ) -> InboundRecord:
        """Clones the InboundRecord for a fresh L1 ingestion replay attempt."""
        resolved_id = new_id or generate_id(self.ID_PREFIX)
        resolved_trace_id = new_trace_id or generate_id(DomainIdPrefix.IP_TRACE.value)
        resolved_parent_id = parent_trace_id or self.trace_id
        next_replay_count = replay_count if replay_count is not None else self.replay_count + 1
        root_trace_id = original_trace_id or self.original_trace_id or self.trace_id
        is_modified = modified_request_body is not None or modified_payload_bytes is not None

        if modified_request_body is not None:
            raw_bytes = (
                modified_payload_bytes
                if modified_payload_bytes is not None
                else json.dumps(
                    modified_request_body, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            )
            req_body: JsonDict | None = dict(modified_request_body)
            req_s3_key: str | None = None
            size_bytes = len(raw_bytes)
            sha256_hash = compute_payload_sha256(raw_bytes)
            is_inlined = True
        elif modified_payload_bytes is not None:
            req_body = self.request_body
            req_s3_key = None
            size_bytes = len(modified_payload_bytes)
            sha256_hash = compute_payload_sha256(modified_payload_bytes)
            is_inlined = True
        else:
            req_body = dict(self.request_body) if self.request_body is not None else None
            req_s3_key = self.request_s3_key
            size_bytes = self.request_size_bytes
            sha256_hash = self.request_sha256
            is_inlined = req_s3_key is None

        cloned = InboundRecord(
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
            ingestion_mode=self.ingestion_mode,
            sync_run_id=self.sync_run_id,
            generation_id=self.generation_id,
            external_event_id=None,
            request_headers=dict(self.request_headers),
            request_body=req_body,
            request_s3_key=req_s3_key,
            request_size_bytes=size_bytes,
            request_sha256=sha256_hash,
            response_status_code=self.response_status_code,
            response_headers=dict(self.response_headers)
            if self.response_headers is not None
            else None,
            response_body=dict(self.response_body) if self.response_body is not None else None,
            response_s3_key=self.response_s3_key,
            duration_ms=self.duration_ms,
            received_at=datetime.now(UTC),
        )

        event_type = (
            IpTraceEventType.MODIFIED_AND_REPLAYED
            if is_modified
            else IpTraceEventType.REPLAY_TRIGGERED
        )
        summary = (
            f"Modified and replayed L1 inbound record from '{resolved_parent_id}' (attempt #{next_replay_count})."
            if is_modified
            else f"Replayed L1 inbound record from '{resolved_parent_id}' (attempt #{next_replay_count})."
        )
        cloned.add_trace_event(
            IpTraceEvent.create(
                tenant_id=self.tenant_id,
                trace_id=resolved_trace_id,
                correlation_id=self.correlation_id,
                event_type=event_type.value,
                actor=actor,
                layer=PipelineLayer.L1_INGEST,
                status=TimelineStatus.RETRIED,
                summary_message=summary,
                replay_metadata=TraceReplayMetadata(
                    parent_trace_id=resolved_parent_id,
                    original_trace_id=root_trace_id,
                    replay_count=next_replay_count,
                ),
            )
        )
        cloned.add_domain_event(
            InboundRecordCreatedEvent(
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
                payload_size_bytes=size_bytes,
                payload_sha256=sha256_hash,
                is_inlined=is_inlined,
                s3_key=req_s3_key,
                ingestion_mode=self.ingestion_mode.value,
                sync_run_id=self.sync_run_id,
                generation_id=self.generation_id,
                external_event_id=None,
            )
        )
        return cloned
