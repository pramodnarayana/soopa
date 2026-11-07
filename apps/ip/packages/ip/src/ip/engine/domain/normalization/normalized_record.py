"""GlobalEntityMap and NormalizedRecord traced aggregate roots for Layer 3."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from seedwork.utils import generate_id
from strace.domain import TracedAggregateRoot, TraceReplayMetadata

from ip.engine.domain.constants import IpIdPrefix
from ip.engine.domain.normalization.events import NormalizedRecordCreatedEvent
from ip.engine.domain.normalization.transformation import CanonicalDataDict
from ip.engine.domain.trace.enums import IpTraceEventType, PipelineStage, TraceEventStatus
from ip.engine.domain.trace.trace_event import IpTraceEvent

__all__ = ["GlobalEntityMap", "NormalizedRecord"]


@dataclass(kw_only=True, eq=False)
class GlobalEntityMap(TracedAggregateRoot):
    """Traced Aggregate Root resolving Source System ID <-> Canonical ID <-> Destination System ID."""

    ID_PREFIX: ClassVar[str] = IpIdPrefix.GEM.value

    id: str
    entity_domain: str
    canonical_id: str
    source_connection_id: str
    source_entity_id: str
    dest_connection_id: str | None = None
    dest_entity_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        trace_id: str,
        entity_domain: str,
        canonical_id: str,
        source_connection_id: str,
        source_entity_id: str,
        dest_connection_id: str | None = None,
        dest_entity_id: str | None = None,
        correlation_id: str | None = None,
        parent_trace_id: str | None = None,
        original_trace_id: str | None = None,
        replay_count: int = 0,
    ) -> GlobalEntityMap:
        return cls(
            id=generate_id(cls.ID_PREFIX),
            tenant_id=tenant_id,
            trace_id=trace_id,
            correlation_id=correlation_id,
            parent_trace_id=parent_trace_id,
            original_trace_id=original_trace_id,
            replay_count=replay_count,
            entity_domain=entity_domain,
            canonical_id=canonical_id,
            source_connection_id=source_connection_id,
            source_entity_id=source_entity_id,
            dest_connection_id=dest_connection_id,
            dest_entity_id=dest_entity_id,
            created_at=datetime.now(UTC),
        )

    def bind_destination(self, dest_connection_id: str, dest_entity_id: str) -> None:
        """Binds the destination connection and external ID once synced."""
        self.dest_connection_id = dest_connection_id
        self.dest_entity_id = dest_entity_id


@dataclass(kw_only=True, eq=False)
class NormalizedRecord(TracedAggregateRoot):
    """Traced Aggregate Root representing a normalized canonical record audit entry in Layer 3."""

    ID_PREFIX: ClassVar[str] = IpIdPrefix.NORMALIZED.value

    id: str
    connection_id: str
    canonical_type: str
    source_id: str
    canonical_data: CanonicalDataDict
    normalized_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        connection_id: str,
        canonical_type: str,
        source_id: str,
        canonical_data: CanonicalDataDict,
        trace_id: str,
        correlation_id: str | None = None,
        parent_trace_id: str | None = None,
        original_trace_id: str | None = None,
        replay_count: int = 0,
    ) -> NormalizedRecord:
        record_id = generate_id(cls.ID_PREFIX)
        type_str = str(canonical_type)
        record = cls(
            id=record_id,
            tenant_id=tenant_id,
            trace_id=trace_id,
            correlation_id=correlation_id,
            parent_trace_id=parent_trace_id,
            original_trace_id=original_trace_id,
            replay_count=replay_count,
            connection_id=connection_id,
            canonical_type=type_str,
            source_id=source_id,
            canonical_data=dict(canonical_data),
            normalized_at=datetime.now(UTC),
        )
        record.add_trace_event(
            IpTraceEvent.create(
                tenant_id=tenant_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                event_type=IpTraceEventType.NORMALIZED.value,
                stage=PipelineStage.NORMALIZE,
                status=TraceEventStatus.SUCCESS,
                summary_message=f"Normalized {type_str} from source '{source_id}'.",
            )
        )
        record.add_domain_event(
            NormalizedRecordCreatedEvent(
                record_id=record_id,
                tenant_id=tenant_id,
                connection_id=connection_id,
                canonical_type=type_str,
                source_id=source_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                parent_trace_id=parent_trace_id,
                original_trace_id=original_trace_id,
                replay_count=replay_count,
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
        modified_canonical_data: CanonicalDataDict | None = None,
        actor: str = "SYSTEM",
    ) -> NormalizedRecord:
        resolved_id = new_id or generate_id(self.ID_PREFIX)
        resolved_trace_id = new_trace_id or generate_id(IpIdPrefix.TRACE.value)
        resolved_parent_id = parent_trace_id or self.trace_id
        root_trace_id = original_trace_id or self.original_trace_id or self.trace_id
        next_replay_count = replay_count if replay_count is not None else self.replay_count + 1
        is_modified = modified_canonical_data is not None
        payload = (
            dict(modified_canonical_data)
            if modified_canonical_data is not None
            else dict(self.canonical_data)
        )

        cloned = NormalizedRecord(
            id=resolved_id,
            tenant_id=self.tenant_id,
            trace_id=resolved_trace_id,
            correlation_id=self.correlation_id,
            parent_trace_id=resolved_parent_id,
            original_trace_id=root_trace_id,
            replay_count=next_replay_count,
            connection_id=self.connection_id,
            canonical_type=self.canonical_type,
            source_id=self.source_id,
            canonical_data=payload,
            normalized_at=datetime.now(UTC),
        )
        event_type = (
            IpTraceEventType.MODIFIED_AND_REPLAYED
            if is_modified
            else IpTraceEventType.REPLAY_TRIGGERED
        )
        summary = (
            f"Modified and replayed canonical {self.canonical_type} from '{resolved_parent_id}' (attempt #{next_replay_count})."
            if is_modified
            else f"Replayed canonical {self.canonical_type} from '{resolved_parent_id}' (attempt #{next_replay_count})."
        )
        cloned.add_trace_event(
            IpTraceEvent.create(
                tenant_id=self.tenant_id,
                trace_id=resolved_trace_id,
                correlation_id=self.correlation_id,
                event_type=event_type.value,
                actor=actor,
                stage=PipelineStage.NORMALIZE,
                status=TraceEventStatus.RETRIED,
                summary_message=summary,
                replay_metadata=TraceReplayMetadata(
                    parent_trace_id=resolved_parent_id,
                    original_trace_id=root_trace_id,
                    replay_count=next_replay_count,
                ),
            )
        )
        cloned.add_domain_event(
            NormalizedRecordCreatedEvent(
                record_id=resolved_id,
                tenant_id=self.tenant_id,
                connection_id=self.connection_id,
                canonical_type=self.canonical_type,
                source_id=self.source_id,
                trace_id=resolved_trace_id,
                correlation_id=self.correlation_id,
                parent_trace_id=resolved_parent_id,
                original_trace_id=root_trace_id,
                replay_count=next_replay_count,
            )
        )
        return cloned
