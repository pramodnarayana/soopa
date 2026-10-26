"""ReplicaRecord traced aggregate root for Layer 2 Universal Replica ledger."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from seedwork.domain.types import JsonDict, JsonPrimitive
from seedwork.id_registry import DomainIdPrefix
from seedwork.utils import generate_id
from strace.domain import TracedAggregateRoot

from ip.engine.domain.enums import (
    CursorKind,
    IpTraceEventType,
    MergeOutcome,
    PipelineLayer,
    TimelineStatus,
)
from ip.engine.domain.events import ReplicaRecordChangedEvent
from ip.engine.domain.models.timeline_entry import IpTraceEvent, TraceReplayMetadata


def compute_record_key(primary_key_values: tuple[JsonPrimitive, ...]) -> str:
    """Computes a deterministic SHA-256 hash of canonicalized primary key values."""
    serialized = json.dumps(list(primary_key_values), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_data_hash(data: JsonDict) -> str:
    """Computes a deterministic SHA-256 hash of canonicalized JSON data for change detection."""
    serialized = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


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
    if cursor_kind == CursorKind.DATETIME:
        try:
            dt_incoming = datetime.fromisoformat(str(incoming_cursor).replace("Z", "+00:00"))
            dt_existing = datetime.fromisoformat(existing_cursor.replace("Z", "+00:00"))
            return dt_incoming < dt_existing
        except (ValueError, TypeError):
            return str(incoming_cursor) < str(existing_cursor)
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
            if existing is not None and existing.deleted_at is not None:
                return MergeOutcome.NOOP
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

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        connection_id: str,
        stream: str,
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
    ) -> ReplicaRecord:
        record_id = generate_id(cls.ID_PREFIX)
        data_hash = compute_data_hash(data)
        actual_key = record_key or compute_record_key(primary_key_values or (stream,))

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
            stream=stream,
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
                summary_message=f"Created L2 replica snapshot for {stream}/{actual_key}.",
            )
        )

        record.add_domain_event(
            ReplicaRecordChangedEvent(
                record_id=record_id,
                tenant_id=tenant_id,
                connection_id=connection_id,
                stream=stream,
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

    @classmethod
    def create_tombstone(
        cls,
        *,
        tenant_id: str,
        connection_id: str,
        stream: str,
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
    ) -> ReplicaRecord:
        """Creates a new replica snapshot directly in the tombstoned (soft-deleted) state."""
        record_id = generate_id(cls.ID_PREFIX)
        data_hash = compute_data_hash(data)
        actual_key = record_key or compute_record_key(primary_key_values or (stream,))

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
            stream=stream,
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
            deleted_at=now,
            source_inbound_record_id=source_inbound_record_id,
        )

        record.add_trace_event(
            IpTraceEvent.create(
                tenant_id=tenant_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                event_type=IpTraceEventType.L2_REPLICA_TOMBSTONED.value,
                layer=PipelineLayer.L2_REPLICA,
                status=TimelineStatus.SUCCESS,
                summary_message=f"Tombstoned L2 replica {stream}/{actual_key} (v1).",
            )
        )

        record.add_domain_event(
            ReplicaRecordChangedEvent(
                record_id=record_id,
                tenant_id=tenant_id,
                connection_id=connection_id,
                stream=stream,
                record_key=actual_key,
                outcome=MergeOutcome.TOMBSTONE.value,
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
        source_inbound_record_id: str | None = None,
    ) -> bool:
        """Updates the replica snapshot if data_hash changed. Returns True if mutated."""
        now = datetime.now(UTC)
        new_hash = compute_data_hash(new_data)
        if new_hash == self.data_hash and self.deleted_at is None:
            if generation_id is not None:
                self.last_seen_generation = generation_id
            self.extracted_at = now
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
        if source_inbound_record_id is not None:
            self.source_inbound_record_id = source_inbound_record_id

        self.version += 1
        self.extracted_at = now
        self.updated_at = now
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
        generation_id: int | None = None,
        source_inbound_record_id: str | None = None,
    ) -> None:
        """Marks the replica snapshot as tombstoned (soft-deleted)."""
        if self.deleted_at is not None:
            return

        now = datetime.now(UTC)
        self.deleted_at = now
        self.extracted_at = now
        self.updated_at = now
        self.version += 1
        self.trace_id = trace_id
        self.correlation_id = correlation_id
        if parent_trace_id is not None:
            self.parent_trace_id = parent_trace_id
        if original_trace_id is not None:
            self.original_trace_id = original_trace_id
        if generation_id is not None:
            self.last_seen_generation = generation_id
        if source_inbound_record_id is not None:
            self.source_inbound_record_id = source_inbound_record_id

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

    def schedule_normalization_replay(
        self,
        *,
        new_trace_id: str | None = None,
        actor: str = "SYSTEM",
    ) -> str:
        """Schedules an L2 -> L3 normalization replay on the current replica snapshot."""
        resolved_trace_id = new_trace_id or generate_id(DomainIdPrefix.IP_TRACE.value)
        root_trace_id = self.original_trace_id or self.trace_id
        prior_trace_id = self.trace_id
        next_replay_count = self.replay_count + 1

        self.parent_trace_id = prior_trace_id
        self.original_trace_id = root_trace_id
        self.replay_count = next_replay_count
        self.trace_id = resolved_trace_id
        self.updated_at = datetime.now(UTC)

        self.add_trace_event(
            IpTraceEvent.create(
                tenant_id=self.tenant_id,
                trace_id=resolved_trace_id,
                correlation_id=self.correlation_id,
                event_type=IpTraceEventType.REPLAY_TRIGGERED.value,
                actor=actor,
                layer=PipelineLayer.L2_REPLICA,
                status=TimelineStatus.RETRIED,
                summary_message=(
                    f"Replayed L2 replica normalization for {self.stream}/{self.record_key} "
                    f"from '{prior_trace_id}' (attempt #{next_replay_count})."
                ),
                replay_metadata=TraceReplayMetadata(
                    parent_trace_id=prior_trace_id,
                    original_trace_id=root_trace_id,
                    replay_count=next_replay_count,
                ),
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
                data_hash=self.data_hash,
                trace_id=resolved_trace_id,
                correlation_id=self.correlation_id,
                parent_trace_id=prior_trace_id,
                original_trace_id=root_trace_id,
                replay_count=next_replay_count,
            )
        )
        return resolved_trace_id


@dataclass(frozen=True)
class ReplicaRejection:
    """Represents a record that could not be extracted or merged at L2."""

    ID_PREFIX: ClassVar[str] = DomainIdPrefix.IP_REPLICA_REJECTION.value

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

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        connection_id: str,
        stream: str,
        inbound_record_id: str,
        record_index: int,
        reason: str,
        detail: str,
        trace_id: str,
        created_at: datetime | None = None,
    ) -> ReplicaRejection:
        return cls(
            id=generate_id(cls.ID_PREFIX),
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream=stream,
            inbound_record_id=inbound_record_id,
            record_index=record_index,
            reason=reason,
            detail=detail,
            trace_id=trace_id,
            created_at=created_at or datetime.now(UTC),
        )
