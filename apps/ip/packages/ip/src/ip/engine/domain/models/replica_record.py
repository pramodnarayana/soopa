"""ReplicaRecord traced aggregate root for Layer 2 Universal Replica ledger."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from seedwork.models import TracedAggregateRoot
from seedwork.utils import generate_id

from ip.engine.domain.constants import IpDomainIdPrefix
from ip.engine.domain.enums import IpTraceEventType, PipelineLayer, TimelineStatus
from ip.engine.domain.events import ReplicaRecordUpdatedEvent
from ip.engine.domain.models.timeline_entry import IpTraceEvent
from ip.engine.domain.types import JsonDict


def compute_replica_hash(data: JsonDict) -> str:
    """Computes a deterministic SHA-256 hash of canonicalized JSON data for change detection."""
    serialized = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(kw_only=True, eq=False)
class ReplicaRecord(TracedAggregateRoot):
    """Traced Aggregate Root representing an unadulterated source entity snapshot in Layer 2."""

    ID_PREFIX: ClassVar[str] = IpDomainIdPrefix.REPLICA

    id: str
    connection_id: str
    app_id: str
    entity_type: str
    entity_id: str
    data: JsonDict
    data_hash: str
    version: int = 1
    synced_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        connection_id: str,
        app_id: str,
        entity_type: str,
        entity_id: str,
        data: JsonDict,
        trace_id: str,
        correlation_id: str | None = None,
        parent_trace_id: str | None = None,
        original_trace_id: str | None = None,
        replay_count: int = 0,
    ) -> ReplicaRecord:
        record_id = generate_id(cls.ID_PREFIX)
        data_hash = compute_replica_hash(data)

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
            entity_type=entity_type,
            entity_id=entity_id,
            data=dict(data),
            data_hash=data_hash,
            version=1,
            synced_at=datetime.now(UTC),
        )

        record.add_trace_event(
            IpTraceEvent.create(
                tenant_id=tenant_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                event_type=IpTraceEventType.L2_REPLICA_CREATED.value,
                layer=PipelineLayer.L2_REPLICA,
                status=TimelineStatus.SUCCESS,
                summary_message=f"Created L2 replica snapshot for {entity_type}/{entity_id}.",
            )
        )

        record.add_domain_event(
            ReplicaRecordUpdatedEvent(
                record_id=record_id,
                tenant_id=tenant_id,
                connection_id=connection_id,
                app_id=app_id,
                entity_type=entity_type,
                entity_id=entity_id,
                data_hash=data_hash,
                trace_id=trace_id,
                correlation_id=correlation_id,
                parent_trace_id=parent_trace_id,
                original_trace_id=original_trace_id,
                replay_count=replay_count,
            )
        )
        return record

    def update_snapshot(
        self,
        *,
        new_data: JsonDict,
        trace_id: str,
        correlation_id: str | None = None,
        parent_trace_id: str | None = None,
        original_trace_id: str | None = None,
        replay_count: int | None = None,
    ) -> bool:
        """Updates the replica snapshot if data_hash changed. Returns True if mutated."""
        new_hash = compute_replica_hash(new_data)
        if new_hash == self.data_hash:
            return False

        self.data = dict(new_data)
        self.data_hash = new_hash
        self.trace_id = trace_id
        self.correlation_id = correlation_id
        if parent_trace_id is not None:
            self.parent_trace_id = parent_trace_id
        if original_trace_id is not None:
            self.original_trace_id = original_trace_id
        if replay_count is not None:
            self.replay_count = replay_count
        self.version += 1
        self.synced_at = datetime.now(UTC)

        self.add_trace_event(
            IpTraceEvent.create(
                tenant_id=self.tenant_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                event_type=IpTraceEventType.L2_REPLICA_UPDATED.value,
                layer=PipelineLayer.L2_REPLICA,
                status=TimelineStatus.SUCCESS,
                summary_message=f"Updated L2 replica snapshot for {self.entity_type}/{self.entity_id} (v{self.version}).",
            )
        )

        self.add_domain_event(
            ReplicaRecordUpdatedEvent(
                record_id=self.id,
                tenant_id=self.tenant_id,
                connection_id=self.connection_id,
                app_id=self.app_id,
                entity_type=self.entity_type,
                entity_id=self.entity_id,
                data_hash=new_hash,
                trace_id=trace_id,
                correlation_id=correlation_id,
                parent_trace_id=self.parent_trace_id,
                original_trace_id=self.original_trace_id,
                replay_count=self.replay_count,
            )
        )
        return True
