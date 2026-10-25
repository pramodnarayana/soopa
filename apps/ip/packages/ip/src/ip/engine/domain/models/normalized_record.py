"""NormalizedRecord traced aggregate root for Layer 3 Canonical Normalization audit ledger."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar

from seedwork.domain.types import JsonValue
from seedwork.id_registry import DomainIdPrefix
from seedwork.models import TracedAggregateRoot
from seedwork.utils import generate_id

from ip.engine.domain.enums import (
    IpTraceEventType,
    PipelineLayer,
    TimelineStatus,
)
from ip.engine.domain.events import NormalizedRecordCreatedEvent
from ip.engine.domain.models.timeline_entry import IpTraceEvent

CanonicalDataValue = JsonValue | Decimal
CanonicalDataDict = dict[str, CanonicalDataValue]


@dataclass(kw_only=True, eq=False)
class NormalizedRecord(TracedAggregateRoot):
    """Traced Aggregate Root representing a normalized canonical record audit entry in Layer 3."""

    ID_PREFIX: ClassVar[str] = DomainIdPrefix.IP_NORMALIZED.value

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
                event_type=IpTraceEventType.L3_NORMALIZED.value,
                layer=PipelineLayer.L3_NORMALIZE,
                status=TimelineStatus.SUCCESS,
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
