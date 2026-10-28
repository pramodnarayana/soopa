"""Strictly-typed Chunk-Pointer Payload DTOs and first-class Result parsers for IP Workers."""

from __future__ import annotations

from dataclasses import dataclass

from ip.engine.domain.enums import (
    CanonicalAction,
    FailureDisposition,
    IngestionMode,
    OutboundDispatchStatus,
    SyncRunKind,
)
from ip.engine.domain.exceptions import IpError, IpErrorCode, Result
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope


def _validation_error(message: str, details: JsonDict | None = None) -> IpError:
    return IpError(
        code=IpErrorCode.VALIDATION_FAILED,
        message=message,
        details=details or {},
        disposition=FailureDisposition.FAIL,
    )


def _extract_non_empty_str(payload: JsonDict, key: str, fallback: str = "") -> str:
    raw = payload.get(key)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return fallback


def _extract_optional_str(payload: JsonDict, key: str) -> str | None:
    raw = payload.get(key)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _extract_int(payload: JsonDict, key: str, default: int) -> int:
    raw = payload.get(key)
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.strip().isdigit():
        return int(raw.strip())
    return default


def _extract_record_ids(
    payload: JsonDict,
    *,
    single_fallback_key: str = "record_id",
) -> tuple[str, ...]:
    raw_ids = payload.get("record_ids")
    if isinstance(raw_ids, (list, tuple)):
        cleaned = tuple(
            str(item).strip()
            for item in raw_ids
            if isinstance(item, (str, int)) and str(item).strip()
        )
        if cleaned:
            return cleaned

    single = payload.get(single_fallback_key)
    if isinstance(single, str) and single.strip():
        return (single.strip(),)
    return ()


@dataclass(frozen=True)
class IpInboundRecordChunkPayloadDTO:
    """Typed chunk-pointer payload for `ip.inbound_record.created` ($N=1$ realtime or $N=K$ bulk)."""

    tenant_id: str
    connection_id: str
    stream_name: str
    record_ids: tuple[str, ...]
    trace_id: str
    correlation_id: str | None = None
    sync_run_id: str | None = None
    generation_id: int = 1
    ingestion_mode: str = IngestionMode.PUSH_FULL.value
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0

    @classmethod
    def from_envelope(
        cls, envelope: EventEnvelope
    ) -> Result[IpInboundRecordChunkPayloadDTO, IpError]:
        p = envelope.payload
        tenant_id = envelope.tenant_id or _extract_non_empty_str(p, "tenant_id")
        connection_id = _extract_non_empty_str(p, "connection_id")
        stream_name = _extract_non_empty_str(p, "stream_name") or _extract_non_empty_str(
            p, "stream"
        )
        record_ids = _extract_record_ids(p, single_fallback_key="record_id")
        trace_id = envelope.trace_id or _extract_non_empty_str(p, "trace_id") or envelope.id
        if not tenant_id or not connection_id or not stream_name or not record_ids:
            return Result.err(
                _validation_error(
                    "Invalid ip.inbound_record.created payload: missing tenant_id, connection_id, stream_name, or record_ids.",
                    {"event_id": envelope.id},
                )
            )
        return Result.ok(
            cls(
                tenant_id=tenant_id,
                connection_id=connection_id,
                stream_name=stream_name,
                record_ids=record_ids,
                trace_id=trace_id,
                correlation_id=envelope.correlation_id
                or _extract_optional_str(p, "correlation_id"),
                sync_run_id=_extract_optional_str(p, "sync_run_id"),
                generation_id=max(1, _extract_int(p, "generation_id", 1)),
                ingestion_mode=_extract_non_empty_str(
                    p, "ingestion_mode", IngestionMode.PUSH_FULL.value
                ),
                parent_trace_id=_extract_optional_str(p, "parent_trace_id"),
                original_trace_id=_extract_optional_str(p, "original_trace_id"),
                replay_count=max(0, _extract_int(p, "replay_count", 0)),
            )
        )


@dataclass(frozen=True)
class IpReplicaRecordChunkPayloadDTO:
    """Typed chunk-pointer payload for `ip.replica_record.changed` ($N=1$ realtime or $N=K$ bulk)."""

    tenant_id: str
    connection_id: str
    stream: str
    record_ids: tuple[str, ...]
    version: int
    trace_id: str
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0

    @classmethod
    def from_envelope(
        cls, envelope: EventEnvelope
    ) -> Result[IpReplicaRecordChunkPayloadDTO, IpError]:
        p = envelope.payload
        tenant_id = envelope.tenant_id or _extract_non_empty_str(p, "tenant_id")
        connection_id = _extract_non_empty_str(p, "connection_id")
        stream = _extract_non_empty_str(p, "stream") or _extract_non_empty_str(p, "stream_name")
        record_ids = _extract_record_ids(p, single_fallback_key="record_id")
        trace_id = envelope.trace_id or _extract_non_empty_str(p, "trace_id") or envelope.id
        if not tenant_id or not connection_id or not stream or not record_ids:
            return Result.err(
                _validation_error(
                    "Invalid ip.replica_record.changed payload: missing tenant_id, connection_id, stream, or record_ids.",
                    {"event_id": envelope.id},
                )
            )
        return Result.ok(
            cls(
                tenant_id=tenant_id,
                connection_id=connection_id,
                stream=stream,
                record_ids=record_ids,
                version=max(1, _extract_int(p, "version", 1)),
                trace_id=trace_id,
                correlation_id=envelope.correlation_id
                or _extract_optional_str(p, "correlation_id"),
                parent_trace_id=_extract_optional_str(p, "parent_trace_id"),
                original_trace_id=_extract_optional_str(p, "original_trace_id"),
                replay_count=max(0, _extract_int(p, "replay_count", 0)),
            )
        )


@dataclass(frozen=True)
class IpNormalizedRecordChunkPayloadDTO:
    """Typed chunk-pointer payload for `ip.normalized_record.created` ($N=1$ realtime or $N=K$ bulk)."""

    tenant_id: str
    connection_id: str
    canonical_type: str
    source_id: str
    record_ids: tuple[str, ...]
    trace_id: str
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0

    @classmethod
    def from_envelope(
        cls, envelope: EventEnvelope
    ) -> Result[IpNormalizedRecordChunkPayloadDTO, IpError]:
        p = envelope.payload
        tenant_id = envelope.tenant_id or _extract_non_empty_str(p, "tenant_id")
        connection_id = _extract_non_empty_str(p, "connection_id")
        canonical_type = _extract_non_empty_str(p, "canonical_type")
        source_id = _extract_non_empty_str(p, "source_id")
        record_ids = _extract_record_ids(p, single_fallback_key="record_id")
        trace_id = envelope.trace_id or _extract_non_empty_str(p, "trace_id") or envelope.id
        if not tenant_id or not canonical_type or not record_ids:
            return Result.err(
                _validation_error(
                    "Invalid ip.normalized_record.created payload: missing tenant_id, canonical_type, or record_ids.",
                    {"event_id": envelope.id},
                )
            )
        return Result.ok(
            cls(
                tenant_id=tenant_id,
                connection_id=connection_id,
                canonical_type=canonical_type,
                source_id=source_id,
                record_ids=record_ids,
                trace_id=trace_id,
                correlation_id=envelope.correlation_id
                or _extract_optional_str(p, "correlation_id"),
                parent_trace_id=_extract_optional_str(p, "parent_trace_id"),
                original_trace_id=_extract_optional_str(p, "original_trace_id"),
                replay_count=max(0, _extract_int(p, "replay_count", 0)),
            )
        )


@dataclass(frozen=True)
class IpCanonicalRecordChunkPayloadDTO:
    """Typed chunk-pointer payload for `ip.canonical_record.changed` ($N=1$ realtime or $N=K$ bulk)."""

    tenant_id: str
    connection_id: str
    canonical_type: str
    record_ids: tuple[str, ...]
    action: str
    transformation_id: str
    transformation_version: int
    replica_id: str
    replica_version: int
    trace_id: str
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0

    @classmethod
    def from_envelope(
        cls, envelope: EventEnvelope
    ) -> Result[IpCanonicalRecordChunkPayloadDTO, IpError]:
        p = envelope.payload
        tenant_id = envelope.tenant_id or _extract_non_empty_str(p, "tenant_id")
        connection_id = _extract_non_empty_str(p, "connection_id")
        canonical_type = _extract_non_empty_str(p, "canonical_type")
        record_ids = _extract_record_ids(p, single_fallback_key="source_id")
        trace_id = envelope.trace_id or _extract_non_empty_str(p, "trace_id") or envelope.id
        if not tenant_id or not canonical_type or not record_ids:
            return Result.err(
                _validation_error(
                    "Invalid ip.canonical_record.changed payload: missing tenant_id, canonical_type, or record_ids.",
                    {"event_id": envelope.id},
                )
            )
        return Result.ok(
            cls(
                tenant_id=tenant_id,
                connection_id=connection_id,
                canonical_type=canonical_type,
                record_ids=record_ids,
                action=_extract_non_empty_str(p, "action", CanonicalAction.UPSERT.value),
                transformation_id=_extract_non_empty_str(p, "transformation_id", "default"),
                transformation_version=max(1, _extract_int(p, "transformation_version", 1)),
                replica_id=_extract_non_empty_str(p, "replica_id"),
                replica_version=max(1, _extract_int(p, "replica_version", 1)),
                trace_id=trace_id,
                correlation_id=envelope.correlation_id
                or _extract_optional_str(p, "correlation_id"),
                parent_trace_id=_extract_optional_str(p, "parent_trace_id"),
                original_trace_id=_extract_optional_str(p, "original_trace_id"),
                replay_count=max(0, _extract_int(p, "replay_count", 0)),
            )
        )


@dataclass(frozen=True)
class IpStreamBackfillPayloadDTO:
    """Typed payload for `ip.transformation.changed` and `ip.transformation_version.promoted`."""

    tenant_id: str
    connection_id: str
    stream: str
    transformation_id: str
    trace_id: str

    @classmethod
    def from_envelope(cls, envelope: EventEnvelope) -> Result[IpStreamBackfillPayloadDTO, IpError]:
        p = envelope.payload
        tenant_id = envelope.tenant_id or _extract_non_empty_str(p, "tenant_id")
        connection_id = _extract_non_empty_str(p, "connection_id")
        stream = _extract_non_empty_str(p, "stream")
        transformation_id = _extract_non_empty_str(p, "transformation_id")
        trace_id = envelope.trace_id or _extract_non_empty_str(p, "trace_id") or envelope.id
        if not tenant_id or not connection_id or not stream:
            return Result.err(
                _validation_error(
                    "Invalid transformation binding/promotion payload: missing tenant_id, connection_id, or stream.",
                    {"event_id": envelope.id},
                )
            )
        return Result.ok(
            cls(
                tenant_id=tenant_id,
                connection_id=connection_id,
                stream=stream,
                transformation_id=transformation_id,
                trace_id=trace_id,
            )
        )


@dataclass(frozen=True)
class IpGenerationCompletedPayloadDTO:
    """Typed payload for `ip.generation.completed`."""

    tenant_id: str
    connection_id: str
    stream: str
    generation_id: int
    trace_id: str

    @classmethod
    def from_envelope(
        cls, envelope: EventEnvelope
    ) -> Result[IpGenerationCompletedPayloadDTO, IpError]:
        p = envelope.payload
        tenant_id = envelope.tenant_id or _extract_non_empty_str(p, "tenant_id")
        connection_id = _extract_non_empty_str(p, "connection_id")
        stream = _extract_non_empty_str(p, "stream")
        generation_id = _extract_int(p, "generation_id", -1)
        trace_id = envelope.trace_id or _extract_non_empty_str(p, "trace_id") or envelope.id
        if not tenant_id or not connection_id or not stream or generation_id < 1:
            return Result.err(
                _validation_error(
                    "Invalid ip.generation.completed payload: missing tenant_id, connection_id, stream, or generation_id.",
                    {"event_id": envelope.id},
                )
            )
        return Result.ok(
            cls(
                tenant_id=tenant_id,
                connection_id=connection_id,
                stream=stream,
                generation_id=generation_id,
                trace_id=trace_id,
            )
        )


@dataclass(frozen=True)
class IpOutboundRecordChunkPayloadDTO:
    """Typed chunk-pointer payload for `ip.outbound_record.created` ($N=1$ realtime or $N=K$ bulk)."""

    tenant_id: str
    connection_id: str
    stream_name: str
    record_ids: tuple[str, ...]
    status: str
    trace_id: str
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0

    @classmethod
    def from_envelope(
        cls, envelope: EventEnvelope
    ) -> Result[IpOutboundRecordChunkPayloadDTO, IpError]:
        p = envelope.payload
        tenant_id = envelope.tenant_id or _extract_non_empty_str(p, "tenant_id")
        connection_id = _extract_non_empty_str(p, "connection_id")
        stream_name = _extract_non_empty_str(p, "stream_name") or _extract_non_empty_str(
            p, "stream"
        )
        record_ids = _extract_record_ids(p, single_fallback_key="record_id")
        status = _extract_non_empty_str(p, "status", OutboundDispatchStatus.PENDING.value)
        trace_id = envelope.trace_id or _extract_non_empty_str(p, "trace_id") or envelope.id
        if not tenant_id or not connection_id or not record_ids:
            return Result.err(
                _validation_error(
                    "Invalid ip.outbound_record.created payload: missing tenant_id, connection_id, or record_ids.",
                    {"event_id": envelope.id},
                )
            )
        return Result.ok(
            cls(
                tenant_id=tenant_id,
                connection_id=connection_id,
                stream_name=stream_name,
                record_ids=record_ids,
                status=status,
                trace_id=trace_id,
                correlation_id=envelope.correlation_id
                or _extract_optional_str(p, "correlation_id"),
                parent_trace_id=_extract_optional_str(p, "parent_trace_id"),
                original_trace_id=_extract_optional_str(p, "original_trace_id"),
                replay_count=max(0, _extract_int(p, "replay_count", 0)),
            )
        )


@dataclass(frozen=True)
class IpFetchRecordChunkPayloadDTO:
    """Typed chunk-pointer payload for `ip.fetch_record.requested` ($N=1$ realtime or $N=K$ bulk)."""

    tenant_id: str
    connection_id: str
    stream_name: str
    record_ids: tuple[str, ...]
    trace_id: str
    correlation_id: str | None = None
    notice_inbound_record_id: str | None = None

    @classmethod
    def from_envelope(
        cls, envelope: EventEnvelope
    ) -> Result[IpFetchRecordChunkPayloadDTO, IpError]:
        p = envelope.payload
        tenant_id = envelope.tenant_id or _extract_non_empty_str(p, "tenant_id")
        connection_id = _extract_non_empty_str(p, "connection_id")
        stream_name = _extract_non_empty_str(p, "stream") or _extract_non_empty_str(
            p, "stream_name"
        )
        record_ids = _extract_record_ids(p, single_fallback_key="record_id")
        trace_id = envelope.trace_id or _extract_non_empty_str(p, "trace_id") or envelope.id
        if not tenant_id or not connection_id or not stream_name or not record_ids:
            return Result.err(
                _validation_error(
                    "Invalid ip.fetch_record.requested payload: missing tenant_id, connection_id, stream, or record_ids.",
                    {"event_id": envelope.id},
                )
            )
        return Result.ok(
            cls(
                tenant_id=tenant_id,
                connection_id=connection_id,
                stream_name=stream_name,
                record_ids=record_ids,
                trace_id=trace_id,
                correlation_id=envelope.correlation_id
                or _extract_optional_str(p, "correlation_id"),
                notice_inbound_record_id=_extract_optional_str(p, "notice_inbound_record_id"),
            )
        )


@dataclass(frozen=True)
class IpSyncRunRequestedPayloadDTO:
    """Typed payload for `ip.sync_run.requested`."""

    tenant_id: str
    connection_id: str
    stream_name: str
    forced_kind: SyncRunKind | None
    trace_id: str
    correlation_id: str | None = None

    @classmethod
    def from_envelope(
        cls, envelope: EventEnvelope
    ) -> Result[IpSyncRunRequestedPayloadDTO, IpError]:
        p = envelope.payload
        tenant_id = envelope.tenant_id or _extract_non_empty_str(p, "tenant_id")
        connection_id = _extract_non_empty_str(p, "connection_id")
        stream_name = _extract_non_empty_str(p, "stream") or _extract_non_empty_str(
            p, "stream_name"
        )
        raw_kind = _extract_optional_str(p, "kind")
        forced_kind: SyncRunKind | None = None
        if raw_kind is not None:
            try:
                forced_kind = SyncRunKind(raw_kind)
            except ValueError:
                return Result.err(
                    _validation_error(
                        f"Invalid SyncRunKind '{raw_kind}' in ip.sync_run.requested.",
                        {"event_id": envelope.id, "kind": raw_kind},
                    )
                )
        trace_id = envelope.trace_id or _extract_non_empty_str(p, "trace_id") or envelope.id
        if not tenant_id or not connection_id or not stream_name:
            return Result.err(
                _validation_error(
                    "Invalid ip.sync_run.requested payload: missing tenant_id, connection_id, or stream.",
                    {"event_id": envelope.id},
                )
            )
        return Result.ok(
            cls(
                tenant_id=tenant_id,
                connection_id=connection_id,
                stream_name=stream_name,
                forced_kind=forced_kind,
                trace_id=trace_id,
                correlation_id=envelope.correlation_id
                or _extract_optional_str(p, "correlation_id"),
            )
        )


__all__ = [
    "IpCanonicalRecordChunkPayloadDTO",
    "IpFetchRecordChunkPayloadDTO",
    "IpGenerationCompletedPayloadDTO",
    "IpInboundRecordChunkPayloadDTO",
    "IpNormalizedRecordChunkPayloadDTO",
    "IpOutboundRecordChunkPayloadDTO",
    "IpReplicaRecordChunkPayloadDTO",
    "IpStreamBackfillPayloadDTO",
    "IpSyncRunRequestedPayloadDTO",
]
