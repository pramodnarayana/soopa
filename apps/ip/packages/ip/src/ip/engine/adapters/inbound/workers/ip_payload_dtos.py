"""Strictly-typed Chunk-Pointer Payload DTOs and first-class Result parsers for IP Workers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ip.engine.domain.dispatch.enums import (
    FailureDisposition,
    OutboundDispatchStatus,
)
from ip.engine.domain.exceptions import IpError, IpErrorCode, Result
from ip.engine.domain.normalization.enums import CanonicalAction
from ip.engine.domain.replication.enums import (
    IngestionMode,
    SyncRunKind,
)
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
    """Typed Range Claim-Check payload for `ip.inbound_record.created` ($K=1$ realtime or $K=N$ bulk)."""

    tenant_id: str
    connection_id: str
    stream_name: str
    record_ids: tuple[str, ...]
    trace_id: str
    batch_id: str = ""
    range_start: str = ""
    range_end: str = ""
    count: int = 1
    causation_depth: int = 0
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
        batch_id = _extract_non_empty_str(p, "batch_id")
        range_start = _extract_non_empty_str(p, "range_start")
        range_end = _extract_non_empty_str(p, "range_end")
        has_range_claim_check = bool(batch_id and range_start and range_end)

        if has_range_claim_check:
            raw_ids = p.get("record_ids")
            if isinstance(raw_ids, (list, tuple)):
                record_ids = tuple(
                    str(item).strip()
                    for item in raw_ids
                    if isinstance(item, (str, int)) and str(item).strip()
                )
            else:
                record_ids = ()
        else:
            record_ids = _extract_record_ids(p, single_fallback_key="record_id")
            if not range_start and record_ids:
                range_start = record_ids[0]
            if not range_end and record_ids:
                range_end = record_ids[-1]

        raw_count = _extract_int(p, "count", 0)
        resolved_count = (
            raw_count
            if raw_count > 0
            else (len(record_ids) if record_ids else (1 if range_start else 0))
        )
        trace_id = envelope.trace_id or _extract_non_empty_str(p, "trace_id") or envelope.id
        if (
            not tenant_id
            or not connection_id
            or not stream_name
            or (not has_range_claim_check and not record_ids)
        ):
            return Result.err(
                _validation_error(
                    "Invalid ip.inbound_record.created payload: missing tenant_id, connection_id, stream_name, or range/record pointers.",
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
                batch_id=batch_id,
                range_start=range_start,
                range_end=range_end,
                count=max(1, resolved_count),
                causation_depth=max(0, _extract_int(p, "causation_depth", 0)),
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
class IpConnectionEntitySubscribedPayloadDTO:
    """Typed payload for `ip.connection_entity.subscribed`."""

    tenant_id: str
    connection_id: str
    entity_id: str
    stream_name: str
    trace_id: str

    @classmethod
    def from_envelope(
        cls, envelope: EventEnvelope
    ) -> Result[IpConnectionEntitySubscribedPayloadDTO, IpError]:
        p = envelope.payload
        tenant_id = envelope.tenant_id or _extract_non_empty_str(p, "tenant_id")
        connection_id = _extract_non_empty_str(p, "connection_id")
        entity_id = _extract_non_empty_str(p, "entity_id")
        stream_name = _extract_non_empty_str(p, "stream_name") or _extract_non_empty_str(
            p, "stream"
        )
        trace_id = envelope.trace_id or _extract_non_empty_str(p, "trace_id") or envelope.id
        if not tenant_id or not connection_id or not stream_name:
            return Result.err(
                _validation_error(
                    "Invalid ip.connection_entity.subscribed payload: missing tenant_id, connection_id, or stream_name.",
                    {"event_id": envelope.id},
                )
            )
        return Result.ok(
            cls(
                tenant_id=tenant_id,
                connection_id=connection_id,
                entity_id=entity_id,
                stream_name=stream_name,
                trace_id=trace_id,
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
    dispatch_headers: Mapping[str, str] = field(default_factory=dict)
    conflict_strategy: str = "FAIL"

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
        raw_headers = p.get("dispatch_headers")
        dispatch_headers = (
            {str(k): str(v) for k, v in raw_headers.items()}
            if isinstance(raw_headers, dict)
            else {}
        )
        conflict_strategy = _extract_non_empty_str(p, "conflict_strategy", "FAIL")
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
                dispatch_headers=dispatch_headers,
                conflict_strategy=conflict_strategy,
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


@dataclass(frozen=True)
class IpIntervalBatchIngestedPayloadDTO:
    """Typed payload for `ip.interval_batch.ingested` (L1 Interval Batch Claim-Check Ticket)."""

    tenant_id: str
    batch_id: str
    connection_id: str
    stream_name: str
    l1_raw_uri: str
    priority_lane: str
    trace_id: str
    correlation_id: str | None = None

    @classmethod
    def from_envelope(
        cls, envelope: EventEnvelope
    ) -> Result[IpIntervalBatchIngestedPayloadDTO, IpError]:
        p = envelope.payload
        tenant_id = envelope.tenant_id or _extract_non_empty_str(p, "tenant_id")
        batch_id = _extract_non_empty_str(p, "batch_id")
        connection_id = _extract_non_empty_str(p, "connection_id")
        stream_name = _extract_non_empty_str(p, "stream_name") or _extract_non_empty_str(
            p, "stream"
        )
        l1_raw_uri = _extract_non_empty_str(p, "l1_raw_uri")
        priority_lane = _extract_non_empty_str(p, "priority_lane", "P1_LIVE")
        trace_id = envelope.trace_id or _extract_non_empty_str(p, "trace_id") or envelope.id
        if not tenant_id or not batch_id:
            return Result.err(
                _validation_error(
                    "Invalid ip.interval_batch.ingested payload: missing tenant_id or batch_id.",
                    {"event_id": envelope.id},
                )
            )
        return Result.ok(
            cls(
                tenant_id=tenant_id,
                batch_id=batch_id,
                connection_id=connection_id,
                stream_name=stream_name,
                l1_raw_uri=l1_raw_uri,
                priority_lane=priority_lane,
                trace_id=trace_id,
                correlation_id=envelope.correlation_id
                or _extract_optional_str(p, "correlation_id"),
            )
        )


@dataclass(frozen=True)
class IpFeederOutageDetectedPayloadDTO:
    """Typed payload for `ip.feeder_outage.detected` (P0_CRITICAL real-time outage cluster bridge)."""

    tenant_id: str
    cluster_id: str
    connection_id: str
    batch_id: str
    feeder_id: str
    substation_id: str
    outage_meter_count: int
    affected_meter_ids: tuple[str, ...]
    outage_start_utc: str
    trace_id: str
    correlation_id: str | None = None

    @classmethod
    def from_envelope(
        cls, envelope: EventEnvelope
    ) -> Result[IpFeederOutageDetectedPayloadDTO, IpError]:
        p = envelope.payload
        tenant_id = envelope.tenant_id or _extract_non_empty_str(p, "tenant_id")
        cluster_id = _extract_non_empty_str(p, "cluster_id")
        connection_id = _extract_non_empty_str(p, "connection_id")
        batch_id = _extract_non_empty_str(p, "batch_id")
        feeder_id = _extract_non_empty_str(p, "feeder_id")
        substation_id = _extract_non_empty_str(p, "substation_id", "SUB-DEFAULT")
        outage_meter_count = max(1, _extract_int(p, "outage_meter_count", 1))
        raw_devices = p.get("affected_meter_ids")
        if isinstance(raw_devices, (list, tuple)):
            affected_meter_ids = tuple(str(m).strip() for m in raw_devices if str(m).strip())
        else:
            affected_meter_ids = ()
        outage_start_utc = _extract_non_empty_str(p, "outage_start_utc")
        trace_id = envelope.trace_id or _extract_non_empty_str(p, "trace_id") or envelope.id
        if not tenant_id or not cluster_id or not feeder_id:
            return Result.err(
                _validation_error(
                    "Invalid ip.feeder_outage.detected payload: missing tenant_id, cluster_id, or feeder_id.",
                    {"event_id": envelope.id},
                )
            )
        return Result.ok(
            cls(
                tenant_id=tenant_id,
                cluster_id=cluster_id,
                connection_id=connection_id,
                batch_id=batch_id,
                feeder_id=feeder_id,
                substation_id=substation_id,
                outage_meter_count=outage_meter_count,
                affected_meter_ids=affected_meter_ids,
                outage_start_utc=outage_start_utc,
                trace_id=trace_id,
                correlation_id=envelope.correlation_id
                or _extract_optional_str(p, "correlation_id"),
            )
        )


__all__ = [
    "IpCanonicalRecordChunkPayloadDTO",
    "IpConnectionEntitySubscribedPayloadDTO",
    "IpFeederOutageDetectedPayloadDTO",
    "IpFetchRecordChunkPayloadDTO",
    "IpGenerationCompletedPayloadDTO",
    "IpInboundRecordChunkPayloadDTO",
    "IpIntervalBatchIngestedPayloadDTO",
    "IpNormalizedRecordChunkPayloadDTO",
    "IpOutboundRecordChunkPayloadDTO",
    "IpReplicaRecordChunkPayloadDTO",
    "IpStreamBackfillPayloadDTO",
    "IpSyncRunRequestedPayloadDTO",
]
