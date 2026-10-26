"""IpTraceEvent domain model extending trace.domain.TraceEvent for the Support Timeline Ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from seedwork.domain.types import JsonDict
from seedwork.id_registry import DomainIdPrefix
from seedwork.utils import generate_id
from strace.domain import TraceErrorDetails, TraceEvent, TraceReplayMetadata

from ip.engine.domain.enums import IpTraceEventType, PipelineLayer, TimelineStatus


@dataclass(kw_only=True)
class IpTraceEvent(TraceEvent):
    """Domain model representing an audit trace event in the immutable IP transaction ledger.

    Inherits from ``trace.domain.TraceEvent`` (``id``, ``tenant_id``, ``trace_id``,
    ``event_type``, ``actor``, ``correlation_id``, ``created_at``, ``metadata``).
    """

    ID_PREFIX: ClassVar[str] = DomainIdPrefix.IP_TRACE_EVENT.value

    @property
    def layer(self) -> PipelineLayer:
        raw = (self.metadata or {}).get("layer", PipelineLayer.L1_INGEST.value)
        return PipelineLayer(str(raw))

    @property
    def status(self) -> TimelineStatus:
        raw = (self.metadata or {}).get("status", TimelineStatus.SUCCESS.value)
        return TimelineStatus(str(raw))

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
        event_type: str = IpTraceEventType.L1_INGEST_RECEIVED.value,
        actor: str = "SYSTEM",
        layer: PipelineLayer,
        status: TimelineStatus,
        summary_message: str,
        error_details: TraceErrorDetails | JsonDict | None = None,
        replay_metadata: TraceReplayMetadata | None = None,
        extra_metadata: JsonDict | None = None,
    ) -> IpTraceEvent:
        meta: JsonDict = {
            "layer": layer.value,
            "status": status.value,
            "summary_message": summary_message,
        }
        if isinstance(error_details, TraceErrorDetails):
            meta["error_details"] = error_details.to_dict()
        elif error_details is not None:
            meta["error_details"] = dict(error_details)
        if replay_metadata is not None:
            meta.update(replay_metadata.to_dict())
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


TimelineEntry = IpTraceEvent

__all__ = [
    "IpTraceEvent",
    "TimelineEntry",
    "TraceErrorDetails",
    "TraceReplayMetadata",
]
