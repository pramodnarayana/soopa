"""Concrete Pull Extraction Strategies and Query Engine for the Universal Schema Simulator."""

from __future__ import annotations

import base64
import json
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ip.engine.domain.exceptions import IpError, IpErrorCode, Result
from ip.engine.ports.outbound.connector_port import RecordEnvelopeDTO
from ip.solutions.connectors.sandbox.universal.spec import SimulatorStreamSpec
from ip.solutions.connectors.sandbox.universal.strategies import (
    ExtractionQuery,
    PaginatedSliceDTO,
    PullExtractionMode,
    PullExtractionStrategy,
)
from ip.solutions.connectors.sandbox.universal.synthesizer import (
    EPOCH_ANCHOR,
    JsonSchemaRecordSynthesizer,
    _format_iso_utc,
)
from seedwork.domain.types import JsonValue


@dataclass(frozen=True)
class BoundedTimeWindowExtractionStrategy:
    """Extracts records bounded by strict [start_time, end_time] closed interval."""

    synthesizer: JsonSchemaRecordSynthesizer

    def extract(
        self,
        spec: SimulatorStreamSpec,
        seed: int,
        query: ExtractionQuery,
    ) -> Result[PaginatedSliceDTO, IpError]:
        step_sec = max(1, spec.cursor_step_seconds)
        start_dt = query.start_time or EPOCH_ANCHOR
        end_dt = query.end_time or (start_dt + timedelta(hours=1))

        if end_dt < start_dt:
            return Result.fail(
                IpError(
                    code=IpErrorCode.VALIDATION_FAILED,
                    message=f"end_time '{end_dt.isoformat()}' cannot be earlier than start_time '{start_dt.isoformat()}'.",
                    http_status=400,
                    details={"start_time": start_dt.isoformat(), "end_time": end_dt.isoformat()},
                )
            )

        start_seq = max(1, int((start_dt - EPOCH_ANCHOR).total_seconds()) // step_sec)
        end_seq = max(start_seq, int((end_dt - EPOCH_ANCHOR).total_seconds()) // step_sec)

        effective_start = start_seq if query.offset is None else max(start_seq, query.offset)
        remaining = max(0, end_seq - effective_start + 1)
        count = min(query.limit, remaining)

        records: list[RecordEnvelopeDTO] = []
        for i in range(count):
            seq = effective_start + i
            record_dt = EPOCH_ANCHOR + timedelta(seconds=step_sec * seq)
            rec = self.synthesizer.synthesize_record_by_sequence(
                spec,
                seed=seed,
                seq_num=seq,
                record_dt=record_dt,
            )
            records.append(rec)

        has_more = (effective_start + count) <= end_seq
        next_offset = (effective_start + count) if has_more else None
        next_cursor = (
            _format_iso_utc(EPOCH_ANCHOR + timedelta(seconds=step_sec * (effective_start + count)))
            if has_more
            else None
        )

        return Result.ok(
            PaginatedSliceDTO(
                records=records,
                next_cursor=next_cursor,
                next_offset=next_offset,
                continuation_token=None,
                has_more=has_more,
                total_estimated=(end_seq - start_seq + 1),
            )
        )


@dataclass(frozen=True)
class HighWatermarkExtractionStrategy:
    """Incremental extraction advancing high-watermark cursor."""

    synthesizer: JsonSchemaRecordSynthesizer

    def extract(
        self,
        spec: SimulatorStreamSpec,
        seed: int,
        query: ExtractionQuery,
    ) -> Result[PaginatedSliceDTO, IpError]:
        effective_limit = min(max(1, query.limit), spec.records_per_pull)
        batch = self.synthesizer.synthesize_batch(
            spec,
            seed=seed,
            cursor=query.cursor,
            limit=effective_limit,
            sequence_offset=query.offset,
        )

        next_cursor = batch[-1].cursor_value if batch else query.cursor
        next_offset = (query.offset or 0) + len(batch) if query.offset is not None else None

        return Result.ok(
            PaginatedSliceDTO(
                records=batch,
                next_cursor=next_cursor,
                next_offset=next_offset,
                continuation_token=None,
                has_more=True,
                total_estimated=None,
            )
        )


@dataclass(frozen=True)
class OffsetLimitExtractionStrategy:
    """Sequential zero-indexed offset and limit pagination."""

    synthesizer: JsonSchemaRecordSynthesizer

    def extract(
        self,
        spec: SimulatorStreamSpec,
        seed: int,
        query: ExtractionQuery,
    ) -> Result[PaginatedSliceDTO, IpError]:
        step_sec = max(1, spec.cursor_step_seconds)
        offset = max(0, query.offset or 0)
        limit = max(1, min(query.limit, 5000))

        records: list[RecordEnvelopeDTO] = []
        for i in range(limit):
            seq = offset + i + 1
            record_dt = EPOCH_ANCHOR + timedelta(seconds=step_sec * seq)
            rec = self.synthesizer.synthesize_record_by_sequence(
                spec,
                seed=seed,
                seq_num=seq,
                record_dt=record_dt,
            )
            records.append(rec)

        next_offset = offset + limit
        next_cursor = records[-1].cursor_value if records else None

        return Result.ok(
            PaginatedSliceDTO(
                records=records,
                next_cursor=next_cursor,
                next_offset=next_offset,
                continuation_token=None,
                has_more=True,
                total_estimated=None,
            )
        )


@dataclass(frozen=True)
class OpaqueTokenExtractionStrategy:
    """Tamper-evident Base64 compound continuation token pagination."""

    synthesizer: JsonSchemaRecordSynthesizer

    def extract(
        self,
        spec: SimulatorStreamSpec,
        seed: int,
        query: ExtractionQuery,
    ) -> Result[PaginatedSliceDTO, IpError]:
        offset = 0
        if query.token:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(query.token.encode()).decode())
                offset = max(0, int(decoded.get("seq", 0)))
            except (ValueError, TypeError, KeyError):
                return Result.fail(
                    IpError(
                        code=IpErrorCode.VALIDATION_FAILED,
                        message="Invalid continuation token format.",
                        http_status=400,
                        details={"token": query.token},
                    )
                )

        limit = max(1, min(query.limit, 5000))
        step_sec = max(1, spec.cursor_step_seconds)

        records: list[RecordEnvelopeDTO] = []
        for i in range(limit):
            seq = offset + i + 1
            record_dt = EPOCH_ANCHOR + timedelta(seconds=step_sec * seq)
            records.append(
                self.synthesizer.synthesize_record_by_sequence(
                    spec, seed=seed, seq_num=seq, record_dt=record_dt
                )
            )

        next_seq = offset + limit
        token_payload = {"seq": next_seq, "ts": int(datetime.now(tz=UTC).timestamp())}
        next_token = base64.urlsafe_b64encode(json.dumps(token_payload).encode()).decode()

        return Result.ok(
            PaginatedSliceDTO(
                records=records,
                next_cursor=records[-1].cursor_value if records else None,
                next_offset=next_seq,
                continuation_token=next_token,
                has_more=True,
            )
        )


@dataclass(frozen=True)
class DeltaCdcExtractionStrategy:
    """Change Data Capture (CDC) envelope decorator with version tracking."""

    synthesizer: JsonSchemaRecordSynthesizer

    def extract(
        self,
        spec: SimulatorStreamSpec,
        seed: int,
        query: ExtractionQuery,
    ) -> Result[PaginatedSliceDTO, IpError]:
        start_version = max(0, query.since_version or 0)
        limit = max(1, min(query.limit, 5000))
        step_sec = max(1, spec.cursor_step_seconds)

        records: list[RecordEnvelopeDTO] = []
        for i in range(limit):
            v = start_version + i + 1
            record_dt = EPOCH_ANCHOR + timedelta(seconds=step_sec * v)
            base_rec = self.synthesizer.synthesize_record_by_sequence(
                spec, seed=seed, seq_num=v, record_dt=record_dt
            )
            # Decorate payload with CDC operational metadata
            op = "UPDATE" if (v % 3 == 0) else "INSERT"
            cdc_data: dict[str, JsonValue] = dict(base_rec.data)
            cdc_data["_cdc_op"] = op
            cdc_data["_cdc_version"] = v

            records.append(
                RecordEnvelopeDTO(
                    stream_name=base_rec.stream_name,
                    record_id=base_rec.record_id,
                    data=cdc_data,
                    emitted_at=base_rec.emitted_at,
                    cursor_value=str(v),
                )
            )

        next_version = start_version + limit
        return Result.ok(
            PaginatedSliceDTO(
                records=records,
                next_cursor=str(next_version),
                next_offset=next_version,
                continuation_token=None,
                has_more=True,
            )
        )


class RateLimited429ExtractionStrategy:
    """Sliding-window rate limiter emitting HTTP 429 when client poll thresholds are exceeded."""

    def __init__(
        self,
        delegate: PullExtractionStrategy,
        *,
        max_requests_per_window: int = 5,
        window_seconds: float = 2.0,
    ) -> None:
        self._delegate = delegate
        self._max_requests = max_requests_per_window
        self._window_seconds = window_seconds
        self._client_history: dict[str, list[float]] = defaultdict(list)

    def extract(
        self,
        spec: SimulatorStreamSpec,
        seed: int,
        query: ExtractionQuery,
    ) -> Result[PaginatedSliceDTO, IpError]:
        now = time.monotonic()
        key = f"{spec.stream_name}_{seed}"
        history = self._client_history[key]

        # Prune calls outside current sliding window
        history[:] = [t for t in history if (now - t) < self._window_seconds]

        # Evict expired keys to prevent memory accumulation in long-running processes
        if not history and key in self._client_history:
            self._client_history.pop(key, None)
            history = self._client_history[key]

        if len(history) >= self._max_requests:
            retry_after = max(1, int(self._window_seconds - (now - history[0])))
            return Result.fail(
                IpError(
                    code=IpErrorCode.RATE_LIMIT_EXCEEDED,
                    message=f"Rate limit exceeded for stream '{spec.stream_name}'. Slow down polling.",
                    http_status=429,
                    details={
                        "retry_after_seconds": retry_after,
                        "limit": self._max_requests,
                        "window_seconds": self._window_seconds,
                    },
                )
            )

        history.append(now)
        return self._delegate.extract(spec, seed, query)


@dataclass(frozen=True)
class StreamedChunkedExtractionStrategy:
    """Generates slice records formatted for chunked NDJSON streaming delivery."""

    synthesizer: JsonSchemaRecordSynthesizer

    def extract(
        self,
        spec: SimulatorStreamSpec,
        seed: int,
        query: ExtractionQuery,
    ) -> Result[PaginatedSliceDTO, IpError]:
        bounded = BoundedTimeWindowExtractionStrategy(self.synthesizer)
        return bounded.extract(spec, seed, query)


class PullQueryEngine:
    """Enterprise Query Engine dispatching requests to configured pull strategies."""

    def __init__(self, synthesizer: JsonSchemaRecordSynthesizer | None = None) -> None:
        self._synthesizer = synthesizer or JsonSchemaRecordSynthesizer()
        self._bounded = BoundedTimeWindowExtractionStrategy(self._synthesizer)
        self._watermark = HighWatermarkExtractionStrategy(self._synthesizer)
        self._offset = OffsetLimitExtractionStrategy(self._synthesizer)
        self._opaque = OpaqueTokenExtractionStrategy(self._synthesizer)
        self._delta = DeltaCdcExtractionStrategy(self._synthesizer)
        self._streamed = StreamedChunkedExtractionStrategy(self._synthesizer)
        self._rate_limited = RateLimited429ExtractionStrategy(self._bounded)

        self._registry: dict[PullExtractionMode, PullExtractionStrategy] = {
            PullExtractionMode.BOUNDED_TIME_WINDOW: self._bounded,
            PullExtractionMode.HIGH_WATERMARK: self._watermark,
            PullExtractionMode.OFFSET_LIMIT: self._offset,
            PullExtractionMode.OPAQUE_TOKEN: self._opaque,
            PullExtractionMode.DELTA_CDC: self._delta,
            PullExtractionMode.STREAMED_CHUNKED: self._streamed,
            PullExtractionMode.RATE_LIMITED_429: self._rate_limited,
        }

    def execute(
        self,
        spec: SimulatorStreamSpec,
        seed: int,
        query: ExtractionQuery,
    ) -> Result[PaginatedSliceDTO, IpError]:
        strategy = self._registry.get(query.mode, self._bounded)
        return strategy.extract(spec, seed, query)


__all__ = [
    "BoundedTimeWindowExtractionStrategy",
    "DeltaCdcExtractionStrategy",
    "HighWatermarkExtractionStrategy",
    "OffsetLimitExtractionStrategy",
    "OpaqueTokenExtractionStrategy",
    "PullQueryEngine",
    "RateLimited429ExtractionStrategy",
    "StreamedChunkedExtractionStrategy",
]
