"""L0/L1 Shock-Absorber use case for buffering high-frequency interval macro-batches."""

from __future__ import annotations

import contextlib
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from seedwork.utils import generate_id

from ip.engine.domain.connection.enums import ConnectionStatus
from ip.engine.domain.constants import IpIdPrefix
from ip.engine.domain.exceptions import (
    ConnectionDeactivatedError,
    ConnectionNotFoundError,
    ConnectionPendingAuthError,
    IntervalMalformedBatchError,
    IpError,
    Result,
)
from ip.engine.domain.intervals.enums import (
    BatchManifestStatus,
    IntervalPayloadFormat,
    PriorityLane,
)
from ip.engine.domain.intervals.models import BatchManifest
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class BufferRawIntervalBatchCommand:
    """Command to ingest and buffer an interval macro-batch at the L1 perimeter."""

    tenant_id: str
    connection_id: str
    stream_name: str
    payload_bytes: bytes
    payload_format: IntervalPayloadFormat = IntervalPayloadFormat.JSON_ARRAY
    priority_lane: PriorityLane = PriorityLane.P1_LIVE
    window_start_utc: datetime | None = None
    window_end_utc: datetime | None = None
    declared_record_count: int | None = None
    trace_id: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class BufferRawIntervalBatchResponse:
    """Response returned upon L1 Shock-Absorber batch acknowledgement (HTTP 202 Accepted)."""

    batch_id: str
    tenant_id: str
    connection_id: str
    stream_name: str
    status: BatchManifestStatus
    priority_lane: PriorityLane
    l1_raw_uri: str
    payload_sha256: str
    payload_size_bytes: int
    raw_ingested_count: int
    window_start_utc: datetime
    window_end_utc: datetime
    trace_id: str
    is_duplicate: bool = False


def _extract_timestamps_from_json_items(items: list[object]) -> list[datetime]:
    timestamps: list[datetime] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ts_raw = item.get("interval_end_utc") or item.get("timestamp")
        if not isinstance(ts_raw, str):
            continue
        try:
            parsed_ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            if parsed_ts.tzinfo is None:
                parsed_ts = parsed_ts.replace(tzinfo=UTC)
            timestamps.append(parsed_ts)
        except ValueError:
            continue
    return timestamps


def _inspect_json_batch_metadata(
    payload_bytes: bytes,
    resolved_start: datetime,
    resolved_end: datetime,
    window_start: datetime | None,
    window_end: datetime | None,
) -> Result[tuple[int, datetime, datetime], IntervalMalformedBatchError]:
    try:
        decoded = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return Result.fail(
            IntervalMalformedBatchError.with_reason(
                f"Invalid JSON in interval batch payload: {exc}"
            )
        )
    if isinstance(decoded, dict) and isinstance(decoded.get("readings"), list):
        items = decoded["readings"]
    elif isinstance(decoded, list):
        items = decoded
    else:
        return Result.fail(
            IntervalMalformedBatchError.with_reason(
                "JSON interval batch must be a JSON array or an object containing a 'readings' list."
            )
        )
    if not items:
        return Result.fail(
            IntervalMalformedBatchError.with_reason("Interval batch contains 0 interval readings.")
        )
    timestamps = _extract_timestamps_from_json_items(items)
    if timestamps:
        resolved_start = window_start or min(timestamps)
        resolved_end = window_end or max(timestamps)
    return Result.ok((len(items), resolved_start, resolved_end))


def _inspect_raw_batch_metadata(
    payload_bytes: bytes,
    payload_format: IntervalPayloadFormat,
    declared_count: int | None,
    window_start: datetime | None,
    window_end: datetime | None,
) -> Result[tuple[int, datetime, datetime], IntervalMalformedBatchError]:
    """Extracts record count and interval window bounds from raw batch bytes if not explicitly declared."""
    now = datetime.now(UTC)
    resolved_start = window_start or now
    resolved_end = window_end or now

    if not payload_bytes:
        return Result.fail(
            IntervalMalformedBatchError.with_reason(
                "Interval batch payload cannot be empty (0 bytes)."
            )
        )

    if declared_count is not None and declared_count > 0:
        return Result.ok((declared_count, resolved_start, resolved_end))

    if payload_format is IntervalPayloadFormat.JSON_ARRAY:
        return _inspect_json_batch_metadata(
            payload_bytes, resolved_start, resolved_end, window_start, window_end
        )

    if payload_format is IntervalPayloadFormat.CSV:
        lines = [
            line.strip()
            for line in payload_bytes.decode("utf-8", errors="replace").splitlines()
            if line.strip()
        ]
        if len(lines) <= 1:
            return Result.fail(
                IntervalMalformedBatchError.with_reason(
                    "CSV interval batch must contain a header row and at least 1 data row."
                )
            )
        return Result.ok((len(lines) - 1, resolved_start, resolved_end))

    return Result.ok((declared_count or 0, resolved_start, resolved_end))


def _build_batch_response(
    manifest: BatchManifest,
    *,
    is_duplicate: bool,
) -> BufferRawIntervalBatchResponse:
    return BufferRawIntervalBatchResponse(
        batch_id=manifest.id,
        tenant_id=manifest.tenant_id,
        connection_id=manifest.connection_id,
        stream_name=manifest.stream_name,
        status=manifest.status,
        priority_lane=manifest.priority_lane,
        l1_raw_uri=manifest.l1_raw_uri,
        payload_sha256=manifest.payload_sha256,
        payload_size_bytes=manifest.payload_size_bytes,
        raw_ingested_count=manifest.raw_ingested_count,
        window_start_utc=manifest.window_start_utc,
        window_end_utc=manifest.window_end_utc,
        trace_id=manifest.trace_id,
        is_duplicate=is_duplicate,
    )


class BufferRawIntervalBatchUseCase:
    """Buffers an incoming interval batch to S3/tiered storage and records its BatchManifest."""

    def __init__(
        self,
        cp_uow: IpControlPlaneUnitOfWorkPort,
        dp_uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        storage: TieredStoragePort,
    ) -> None:
        self._cp_uow = cp_uow
        self._dp_uow_provider = dp_uow_provider
        self._storage = storage

    async def _validate_connection(
        self,
        tenant_id: str,
        connection_id: str,
        bound_log: structlog.stdlib.BoundLogger,
    ) -> Result[str, IpError]:
        async with self._cp_uow as cp:
            connection = await cp.connections.get_by_id(connection_id)
            if connection is None or connection.tenant_id != tenant_id:
                bound_log.error("interval_ingress_connection_not_found")
                return Result.fail(ConnectionNotFoundError.for_id(connection_id))
            if connection.status is ConnectionStatus.DEACTIVATED:
                bound_log.error("interval_ingress_connection_deactivated")
                return Result.fail(ConnectionDeactivatedError.for_id(connection_id))
            if connection.status is ConnectionStatus.PENDING_AUTH:
                bound_log.error("interval_ingress_connection_pending_auth")
                return Result.fail(ConnectionPendingAuthError.for_connection(connection_id))
            return Result.ok(connection.app_id)

    async def _handle_save_conflict(
        self,
        command: BufferRawIntervalBatchCommand,
        shard_id: str,
        shard_dsn: str,
        payload_sha256: str,
        storage_s3_key: str | None,
        bound_log: structlog.stdlib.BoundLogger,
    ) -> BufferRawIntervalBatchResponse | None:
        if storage_s3_key is not None and hasattr(self._storage, "delete"):
            with contextlib.suppress(OSError, RuntimeError):
                await self._storage.delete(storage_s3_key)
        async with self._dp_uow_provider.get_data_plane_uow(
            command.tenant_id, shard_id, shard_dsn
        ) as recovery_uow:
            winner = await recovery_uow.batch_manifests.get_by_sha256(
                command.tenant_id, command.connection_id, payload_sha256
            )
            if winner is not None:
                bound_log.info(
                    "interval_batch_duplicate_recovered_on_conflict",
                    batch_id=winner.id,
                    payload_sha256=payload_sha256,
                )
                return _build_batch_response(winner, is_duplicate=True)
        return None

    async def execute(
        self,
        command: BufferRawIntervalBatchCommand,
    ) -> Result[BufferRawIntervalBatchResponse, IpError]:
        bound_log = logger.bind(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream_name=command.stream_name,
            priority_lane=command.priority_lane.value,
        )

        conn_res = await self._validate_connection(
            command.tenant_id, command.connection_id, bound_log
        )
        if conn_res.is_err:
            return Result.fail(conn_res.unwrap_err())
        app_id = conn_res.unwrap()

        metadata_res = _inspect_raw_batch_metadata(
            payload_bytes=command.payload_bytes,
            payload_format=command.payload_format,
            declared_count=command.declared_record_count,
            window_start=command.window_start_utc,
            window_end=command.window_end_utc,
        )
        if metadata_res.is_err:
            err = metadata_res.unwrap_err()
            bound_log.error(
                "interval_ingress_malformed_batch",
                reason=err.message,
            )
            return Result.fail(err)

        raw_count, window_start_utc, window_end_utc = metadata_res.unwrap()
        payload_sha256 = hashlib.sha256(command.payload_bytes).hexdigest()

        shard_res = await self._dp_uow_provider.resolve_shard_info(command.tenant_id)
        if shard_res.is_err:
            bound_log.error("interval_ingress_shard_not_found")
            return Result.fail(shard_res.unwrap_err())
        shard_id, shard_dsn = shard_res.unwrap()

        async with self._dp_uow_provider.get_data_plane_uow(
            command.tenant_id, shard_id, shard_dsn
        ) as uow:
            existing = await uow.batch_manifests.get_by_sha256(
                command.tenant_id,
                command.connection_id,
                payload_sha256,
            )
            if existing is not None:
                bound_log.info(
                    "interval_batch_duplicate_acknowledged",
                    batch_id=existing.id,
                    payload_sha256=payload_sha256,
                )
                return Result.ok(_build_batch_response(existing, is_duplicate=True))

            resolved_trace_id = command.trace_id or generate_id(IpIdPrefix.TRACE.value)
            resolved_batch_id = generate_id(IpIdPrefix.INTERVAL_BATCH.value)
            storage_dto = await self._storage.store(
                tenant_id=command.tenant_id,
                trace_id=resolved_trace_id,
                payload_bytes=command.payload_bytes,
            )
            l1_raw_uri = (
                f"s3://{storage_dto.s3_key}"
                if storage_dto.s3_key is not None
                else f"inline://{resolved_batch_id}"
            )

            manifest = BatchManifest.create_ingested(
                batch_id=resolved_batch_id,
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                app_id=app_id,
                stream_name=command.stream_name,
                l1_raw_uri=l1_raw_uri,
                inline_payload=storage_dto.raw_payload,
                payload_sha256=payload_sha256,
                payload_size_bytes=storage_dto.payload_size_bytes,
                raw_ingested_count=raw_count,
                window_start_utc=window_start_utc,
                window_end_utc=window_end_utc,
                priority_lane=command.priority_lane,
                payload_format=command.payload_format,
                trace_id=resolved_trace_id,
                correlation_id=command.correlation_id,
            )

            try:
                await uow.batch_manifests.save(manifest)
                await uow.commit()
            except Exception as exc:
                is_conflict = (
                    "unique" in str(exc).lower() or "integrity" in type(exc).__name__.lower()
                )
                if is_conflict:
                    recovered = await self._handle_save_conflict(
                        command=command,
                        shard_id=shard_id,
                        shard_dsn=shard_dsn,
                        payload_sha256=payload_sha256,
                        storage_s3_key=storage_dto.s3_key,
                        bound_log=bound_log,
                    )
                    if recovered is not None:
                        return Result.ok(recovered)
                raise

        bound_log.info(
            "interval_batch_buffered",
            batch_id=manifest.id,
            trace_id=manifest.trace_id,
            raw_ingested_count=manifest.raw_ingested_count,
            payload_size_bytes=manifest.payload_size_bytes,
            l1_raw_uri=manifest.l1_raw_uri,
        )
        return Result.ok(_build_batch_response(manifest, is_duplicate=False))


__all__ = [
    "BufferRawIntervalBatchCommand",
    "BufferRawIntervalBatchResponse",
    "BufferRawIntervalBatchUseCase",
]
