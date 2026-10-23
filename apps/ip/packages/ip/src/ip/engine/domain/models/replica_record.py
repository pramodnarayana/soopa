"""ReplicaRecord traced aggregate root for Layer 2 Universal Replica ledger."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from seedwork.domain.types import JsonDict, JsonPrimitive
from seedwork.id_registry import DomainIdPrefix
from seedwork.models import TracedAggregateRoot
from seedwork.utils import generate_id

from ip.engine.domain.enums import (
    CursorKind,
    IpTraceEventType,
    MergeOutcome,
    PipelineLayer,
    TimelineStatus,
)
from ip.engine.domain.events import ReplicaRecordChangedEvent
from ip.engine.domain.models.timeline_entry import IpTraceEvent


def compute_record_key(primary_key_values: tuple[JsonPrimitive, ...]) -> str:
    """Computes a deterministic SHA-256 hash of canonicalized primary key values."""
    serialized = json.dumps(list(primary_key_values), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_data_hash(data: JsonDict) -> str:
    """Computes a deterministic SHA-256 hash of canonicalized JSON data for change detection."""
    serialized = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# Backward compatibility alias
compute_replica_hash = compute_data_hash


def _is_cursor_stale(
    existing_cursor: str,
    incoming_cursor: str | int | float,
    cursor_kind: CursorKind,
) -> bool:
    """Checks whether the incoming cursor value is older than the existing cursor value."""
    if cursor_kind == CursorKind.INTEGER:
        try:
            return int(incoming_cursor) < int(existing_cursor)
        except (ValueError, TypeError):
            return False
    return str(incoming_cursor) < str(existing_cursor)


class ReplicaMergePolicy:
    """Pure domain merge policy determining the lifecycle transition of an incoming replica candidate."""

    @staticmethod
    def evaluate(
        existing: ReplicaRecord | None,
        incoming_data_hash: str,
        incoming_cursor: str | int | float | None = None,
        cursor_kind: CursorKind = CursorKind.STRING,
        is_deleted: bool = False,
    ) -> MergeOutcome:
        if is_deleted:
            return MergeOutcome.TOMBSTONE

        if existing is None:
            return MergeOutcome.INSERT

        if existing.deleted_at is not None:
            return MergeOutcome.UPDATE

        # Out-of-order check
        if (
            existing.cursor_value is not None
            and incoming_cursor is not None
            and _is_cursor_stale(existing.cursor_value, incoming_cursor, cursor_kind)
        ):
            return MergeOutcome.STALE

        if existing.data_hash == incoming_data_hash:
            return MergeOutcome.NOOP

        return MergeOutcome.UPDATE


@dataclass(kw_only=True, eq=False)
class ReplicaRecord(TracedAggregateRoot):
    """Traced Aggregate Root representing an unadulterated source entity snapshot in Layer 2."""

    ID_PREFIX: ClassVar[str] = DomainIdPrefix.IP_REPLICA.value

    id: str
    connection_id: str
    stream: str
    record_key: str
    primary_key_values: tuple[JsonPrimitive, ...] = ()
    cursor_value: str | None = None
    cursor_kind: str | None = None
    data: JsonDict
    data_hash: str
    version: int = 1
    generation_id: int = 1
    last_seen_generation: int = 1
    first_seen_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    extracted_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = None
    source_inbound_record_id: str = ""

    # Backward-compatible convenience properties
    @property
    def entity_type(self) -> str:
        return self.stream

    @property
    def entity_id(self) -> str:
        return self.record_key

    @property
    def app_id(self) -> str:
        return ""

    @property
    def synced_at(self) -> datetime:
        return self.updated_at

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        connection_id: str,
        stream: str | None = None,
        record_key: str | None = None,
        primary_key_values: tuple[JsonPrimitive, ...] = (),
        cursor_value: str | None = None,
        cursor_kind: str | None = None,
        data: JsonDict,
        generation_id: int = 1,
        source_inbound_record_id: str = "",
        trace_id: str,
        correlation_id: str | None = None,
        parent_trace_id: str | None = None,
        original_trace_id: str | None = None,
        replay_count: int = 0,
        # Backward compatibility kwargs
        entity_type: str | None = None,
        entity_id: str | None = None,
        app_id: str | None = None,
    ) -> ReplicaRecord:
        record_id = generate_id(cls.ID_PREFIX)
        data_hash = compute_data_hash(data)
        actual_stream = stream or entity_type or "default"
        actual_key = (
            record_key or entity_id or compute_record_key(primary_key_values or (actual_stream,))
        )

        now = datetime.now(UTC)
        record = cls(
            id=record_id,
            tenant_id=tenant_id,
            trace_id=trace_id,
            correlation_id=correlation_id,
            parent_trace_id=parent_trace_id,
            original_trace_id=original_trace_id,
            replay_count=replay_count,
            connection_id=connection_id,
            stream=actual_stream,
            record_key=actual_key,
            primary_key_values=primary_key_values,
            cursor_value=cursor_value,
            cursor_kind=cursor_kind,
            data=dict(data),
            data_hash=data_hash,
            version=1,
            generation_id=generation_id,
            last_seen_generation=generation_id,
            first_seen_at=now,
            extracted_at=now,
            updated_at=now,
            source_inbound_record_id=source_inbound_record_id,
        )

        record.add_trace_event(
            IpTraceEvent.create(
                tenant_id=tenant_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                event_type=IpTraceEventType.L2_REPLICA_CREATED.value,
                layer=PipelineLayer.L2_REPLICA,
                status=TimelineStatus.SUCCESS,
                summary_message=f"Created L2 replica snapshot for {actual_stream}/{actual_key}.",
            )
        )

        record.add_domain_event(
            ReplicaRecordChangedEvent(
                record_id=record_id,
                tenant_id=tenant_id,
                connection_id=connection_id,
                stream=actual_stream,
                record_key=actual_key,
                outcome=MergeOutcome.INSERT.value,
                version=1,
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
        cursor_value: str | None = None,
        generation_id: int | None = None,
    ) -> bool:
        """Updates the replica snapshot if data_hash changed. Returns True if mutated."""
        new_hash = compute_data_hash(new_data)
        if new_hash == self.data_hash:
            if generation_id is not None:
                self.last_seen_generation = generation_id
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
        if cursor_value is not None:
            self.cursor_value = cursor_value
        if generation_id is not None:
            self.last_seen_generation = generation_id

        self.version += 1
        self.updated_at = datetime.now(UTC)
        self.deleted_at = None

        self.add_trace_event(
            IpTraceEvent.create(
                tenant_id=self.tenant_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                event_type=IpTraceEventType.L2_REPLICA_UPDATED.value,
                layer=PipelineLayer.L2_REPLICA,
                status=TimelineStatus.SUCCESS,
                summary_message=f"Updated L2 replica snapshot for {self.stream}/{self.record_key} (v{self.version}).",
            )
        )

        self.add_domain_event(
            ReplicaRecordChangedEvent(
                record_id=self.id,
                tenant_id=self.tenant_id,
                connection_id=self.connection_id,
                stream=self.stream,
                record_key=self.record_key,
                outcome=MergeOutcome.UPDATE.value,
                version=self.version,
                data_hash=new_hash,
                trace_id=trace_id,
                correlation_id=correlation_id,
                parent_trace_id=self.parent_trace_id,
                original_trace_id=self.original_trace_id,
                replay_count=self.replay_count,
            )
        )
        return True

    def tombstone(
        self,
        *,
        trace_id: str,
        correlation_id: str | None = None,
        parent_trace_id: str | None = None,
        original_trace_id: str | None = None,
    ) -> None:
        """Marks the replica snapshot as tombstoned (soft-deleted)."""
        if self.deleted_at is not None:
            return

        self.deleted_at = datetime.now(UTC)
        self.version += 1
        self.trace_id = trace_id
        self.correlation_id = correlation_id
        if parent_trace_id is not None:
            self.parent_trace_id = parent_trace_id
        if original_trace_id is not None:
            self.original_trace_id = original_trace_id

        self.add_trace_event(
            IpTraceEvent.create(
                tenant_id=self.tenant_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                event_type=IpTraceEventType.L2_REPLICA_TOMBSTONED.value,
                layer=PipelineLayer.L2_REPLICA,
                status=TimelineStatus.SUCCESS,
                summary_message=f"Tombstoned L2 replica {self.stream}/{self.record_key} (v{self.version}).",
            )
        )

        self.add_domain_event(
            ReplicaRecordChangedEvent(
                record_id=self.id,
                tenant_id=self.tenant_id,
                connection_id=self.connection_id,
                stream=self.stream,
                record_key=self.record_key,
                outcome=MergeOutcome.TOMBSTONE.value,
                version=self.version,
                data_hash=self.data_hash,
                trace_id=trace_id,
                correlation_id=correlation_id,
                parent_trace_id=self.parent_trace_id,
                original_trace_id=self.original_trace_id,
                replay_count=self.replay_count,
            )
        )


@dataclass(frozen=True)
class ReplicaRejection:
    """Represents a record that could not be extracted or merged at L2."""

    id: str
    tenant_id: str
    connection_id: str
    stream: str
    inbound_record_id: str
    record_index: int
    reason: str
    detail: str
    trace_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
