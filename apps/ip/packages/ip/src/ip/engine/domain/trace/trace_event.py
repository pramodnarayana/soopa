"""Audit trace models for the IP Distributed Tracing & Audit Ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from seedwork.domain.types import JsonDict
from seedwork.utils import generate_id
from strace.domain import TraceErrorDetails, TraceEvent, TraceReplayMetadata

from ip.engine.domain.constants import IpIdPrefix
from ip.engine.domain.enums import PipelineStage
from ip.engine.domain.trace.enums import IpTraceEventType, TraceEventStatus


@dataclass(kw_only=True)
class IpTraceEvent(TraceEvent):
    """Domain model representing an audit trace event in the immutable IP audit ledger.

    Inherits from ``trace.domain.TraceEvent`` (``id``, ``tenant_id``, ``trace_id``,
    ``event_type``, ``actor``, ``correlation_id``, ``created_at``, ``metadata``).
    """

    ID_PREFIX: ClassVar[str] = IpIdPrefix.TRACE_EVENT.value

    @property
    def stage(self) -> PipelineStage:
        """Pipeline execution stage (L1-L5) where this audit event was recorded."""
        raw = (self.metadata or {}).get("stage") or (self.metadata or {}).get(
            "layer", PipelineStage.INGEST.value
        )
        return PipelineStage(str(raw))

    @property
    def status(self) -> TraceEventStatus:
        raw = (self.metadata or {}).get("status", TraceEventStatus.SUCCESS.value)
        return TraceEventStatus(str(raw))

    @property
    def summary_message(self) -> str:
        raw = (self.metadata or {}).get("summary_message", "")
        return str(raw)

    @property
    def error_details(self) -> JsonDict | None:
        raw = (self.metadata or {}).get("error_details")
        return dict(raw) if isinstance(raw, dict) else None

    @property
    def occurred_at(self) -> datetime:
        return self.created_at

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        trace_id: str,
        correlation_id: str | None = None,
        event_type: str = IpTraceEventType.INGEST_RECEIVED.value,
        actor: str = "SYSTEM",
        stage: PipelineStage = PipelineStage.INGEST,
        status: TraceEventStatus,
        summary_message: str,
        error_details: TraceErrorDetails | JsonDict | None = None,
        parent_trace_id: str | None = None,
        original_trace_id: str | None = None,
        replay_count: int | None = None,
        replay_metadata: TraceReplayMetadata | None = None,
        extra_metadata: JsonDict | None = None,
    ) -> IpTraceEvent:
        meta: JsonDict = {
            "stage": stage.value,
            "status": status.value,
            "summary_message": summary_message,
        }
        if isinstance(error_details, TraceErrorDetails):
            meta["error_details"] = error_details.to_dict()
        elif error_details is not None:
            meta["error_details"] = dict(error_details)
        if replay_metadata is not None:
            meta.update(replay_metadata.to_dict())
        if parent_trace_id is not None:
            meta["parent_trace_id"] = parent_trace_id
        if original_trace_id is not None:
            meta["original_trace_id"] = original_trace_id
        if replay_count is not None:
            meta["replay_count"] = replay_count
        if extra_metadata is not None:
            meta.update(extra_metadata)

        return cls(
            id=generate_id(cls.ID_PREFIX),
            tenant_id=tenant_id,
            trace_id=trace_id,
            correlation_id=correlation_id,
            event_type=event_type,
            actor=actor,
            created_at=datetime.now(UTC),
            metadata=meta,
        )


__all__ = [
    "IpTraceEvent",
    "TraceErrorDetails",
]
