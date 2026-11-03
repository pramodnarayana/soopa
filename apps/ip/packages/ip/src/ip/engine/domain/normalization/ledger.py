"""L3 Normalization execution ledger aggregate root, rejections, shadow diffs, and pending refs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from seedwork.domain.types import JsonDict, JsonValue
from seedwork.utils import generate_id
from strace.domain import TracedAggregateRoot, TraceEvent

from ip.engine.domain.constants import IpIdPrefix
from ip.engine.domain.normalization.enums import (
    CanonicalAction,
    NormalizationOutcome,
    PendingReferenceStatus,
)
from ip.engine.domain.normalization.events import CanonicalRecordChangedEvent
from ip.engine.domain.trace.enums import IpTraceEventType, PipelineStage, TraceEventStatus
from ip.engine.domain.trace.trace_event import IpTraceEvent, TraceErrorDetails

__all__ = [
    "EntityShadowDiff",
    "FieldShadowDiff",
    "NormalizationLedgerEntry",
    "NormalizationRejectionEntry",
    "NormalizationShadowDiffEntry",
    "PendingReferenceEntry",
]


@dataclass(kw_only=True, eq=False)
class NormalizationLedgerEntry(TracedAggregateRoot):
    """L3 Traced Aggregate Root tracking replica version normalization outcomes and canonical lineage."""

    ID_PREFIX: ClassVar[str] = IpIdPrefix.NORMALIZATION_LEDGER.value

    id: str
    replica_record_id: str
    replica_version: int
    transformation_id: str
    transformation_version: int
    produced_canonical_refs: tuple[tuple[str, str], ...]
    outcome: NormalizationOutcome
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        replica_record_id: str,
        replica_version: int,
        transformation_id: str,
        transformation_version: int,
        produced_canonical_refs: tuple[tuple[str, str], ...],
        outcome: NormalizationOutcome,
        trace_id: str,
        correlation_id: str | None = None,
        parent_trace_id: str | None = None,
        original_trace_id: str | None = None,
        replay_count: int = 0,
    ) -> NormalizationLedgerEntry:
        return cls(
            id=generate_id(cls.ID_PREFIX),
            tenant_id=tenant_id,
            replica_record_id=replica_record_id,
            replica_version=replica_version,
            transformation_id=transformation_id,
            transformation_version=transformation_version,
            produced_canonical_refs=produced_canonical_refs,
            outcome=outcome,
            trace_id=trace_id,
            correlation_id=correlation_id,
            parent_trace_id=parent_trace_id,
            original_trace_id=original_trace_id,
            replay_count=replay_count,
            created_at=datetime.now(UTC),
        )

    @classmethod
    def begin(
        cls,
        *,
        tenant_id: str,
        replica_record_id: str,
        replica_version: int,
        transformation_id: str,
        transformation_version: int,
        trace_id: str,
        correlation_id: str | None = None,
        parent_trace_id: str | None = None,
        original_trace_id: str | None = None,
        replay_count: int = 0,
    ) -> NormalizationLedgerEntry:
        """Initializes an active L3 normalization execution aggregate for a replica version."""
        return cls.create(
            tenant_id=tenant_id,
            replica_record_id=replica_record_id,
            replica_version=replica_version,
            transformation_id=transformation_id,
            transformation_version=transformation_version,
            produced_canonical_refs=(),
            outcome=NormalizationOutcome.NORMALIZED,
            trace_id=trace_id,
            correlation_id=correlation_id,
            parent_trace_id=parent_trace_id,
            original_trace_id=original_trace_id,
            replay_count=replay_count,
        )

    @classmethod
    def reject_execution(
        cls,
        *,
        tenant_id: str,
        replica_record_id: str,
        replica_version: int,
        transformation_id: str,
        transformation_version: int,
        reason_code: str,
        detail: str,
        summary_message: str,
        trace_id: str,
        correlation_id: str | None = None,
        parent_trace_id: str | None = None,
        original_trace_id: str | None = None,
        replay_count: int = 0,
    ) -> NormalizationLedgerEntry:
        """Creates a rejected L3 ledger entry and records its NORMALIZATION_REJECTED trace event."""
        entry = cls.create(
            tenant_id=tenant_id,
            replica_record_id=replica_record_id,
            replica_version=replica_version,
            transformation_id=transformation_id,
            transformation_version=transformation_version,
            produced_canonical_refs=(),
            outcome=NormalizationOutcome.REJECTED,
            trace_id=trace_id,
            correlation_id=correlation_id,
            parent_trace_id=parent_trace_id,
            original_trace_id=original_trace_id,
            replay_count=replay_count,
        )
        entry._append_normalize_trace(
            event_type=IpTraceEventType.NORMALIZATION_REJECTED,
            status=TraceEventStatus.FAILED,
            summary_message=summary_message,
            error_details=TraceErrorDetails(reason=reason_code, detail=detail),
        )
        return entry

    def record_pending_reference(
        self,
        *,
        field_name: str,
        target_canonical_type: str,
        target_source_id: str,
    ) -> None:
        """Records an unresolved pending canonical reference trace during draft application."""
        self._append_normalize_trace(
            event_type=IpTraceEventType.REFERENCE_PENDING,
            status=TraceEventStatus.SUCCESS,
            summary_message=(
                f"Recorded pending reference '{field_name}' -> "
                f"({target_canonical_type}, {target_source_id})."
            ),
        )

    def record_canonical_upsert(
        self,
        *,
        connection_id: str,
        canonical_type: str,
        source_id: str,
        changed_fields: tuple[str, ...] = (),
    ) -> None:
        """Records a produced canonical entity upsert and stages CanonicalRecordChangedEvent."""
        self.produced_canonical_refs = (*self.produced_canonical_refs, (canonical_type, source_id))
        self.add_domain_event(
            CanonicalRecordChangedEvent(
                tenant_id=self.tenant_id,
                connection_id=connection_id,
                canonical_type=canonical_type,
                source_id=source_id,
                action=CanonicalAction.UPSERT.value,
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
                transformation_id=self.transformation_id,
                transformation_version=self.transformation_version,
                replica_id=self.replica_record_id,
                replica_version=self.replica_version,
                changed_fields=changed_fields,
                parent_trace_id=self.parent_trace_id,
                original_trace_id=self.original_trace_id,
                replay_count=self.replay_count,
            )
        )

    def record_canonical_tombstone(
        self,
        *,
        connection_id: str,
        canonical_type: str,
        source_id: str,
    ) -> None:
        """Stages CanonicalRecordChangedEvent(TOMBSTONE) for a soft-deleted canonical entity."""
        self.add_domain_event(
            CanonicalRecordChangedEvent(
                tenant_id=self.tenant_id,
                connection_id=connection_id,
                canonical_type=canonical_type,
                source_id=source_id,
                action=CanonicalAction.TOMBSTONE.value,
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
                transformation_id=self.transformation_id,
                transformation_version=self.transformation_version,
                replica_id=self.replica_record_id,
                replica_version=self.replica_version,
                parent_trace_id=self.parent_trace_id,
                original_trace_id=self.original_trace_id,
                replay_count=self.replay_count,
            )
        )

    def record_unseen_draft_tombstone(
        self,
        *,
        connection_id: str,
        canonical_type: str,
        source_id: str,
    ) -> None:
        """Records both CanonicalRecordChangedEvent(TOMBSTONE) and trace for an unseen prior draft."""
        self.record_canonical_tombstone(
            connection_id=connection_id,
            canonical_type=canonical_type,
            source_id=source_id,
        )
        self._append_normalize_trace(
            event_type=IpTraceEventType.TOMBSTONED,
            status=TraceEventStatus.SUCCESS,
            summary_message=f"Tombstoned unseen canonical draft ({canonical_type}, {source_id}).",
        )

    def record_resolved_reference(
        self,
        *,
        field_name: str,
        referencing_canonical_type: str,
        referencing_source_id: str,
        target_id: str,
    ) -> None:
        """Records a late-arriving canonical reference back-patch trace."""
        self._append_normalize_trace(
            event_type=IpTraceEventType.REFERENCE_RESOLVED,
            status=TraceEventStatus.SUCCESS,
            summary_message=(
                f"Resolved pending reference '{field_name}' on "
                f"({referencing_canonical_type}, {referencing_source_id}) -> {target_id}."
            ),
        )

    def complete_tombstone(self, *, tombstoned_count: int) -> NormalizationOutcome:
        """Finalizes a replica tombstone cascade and records the summary TOMBSTONED trace."""
        self.produced_canonical_refs = ()
        self.outcome = NormalizationOutcome.TOMBSTONED
        self._append_normalize_trace(
            event_type=IpTraceEventType.TOMBSTONED,
            status=TraceEventStatus.SUCCESS,
            summary_message=(
                f"Tombstoned {tombstoned_count} canonical record(s) from replica '{self.replica_record_id}'."
            ),
        )
        return self.outcome

    def complete_normalization(self, *, rejections_count: int) -> NormalizationOutcome:
        """Determines terminal normalization outcome and records the summary L3 trace event."""
        outcome = (
            NormalizationOutcome.NORMALIZED
            if self.produced_canonical_refs or rejections_count == 0
            else NormalizationOutcome.REJECTED
        )
        self.outcome = outcome
        is_normalized = outcome == NormalizationOutcome.NORMALIZED
        self._append_normalize_trace(
            event_type=(
                IpTraceEventType.NORMALIZED
                if is_normalized
                else IpTraceEventType.NORMALIZATION_REJECTED
            ),
            status=TraceEventStatus.SUCCESS if is_normalized else TraceEventStatus.FAILED,
            summary_message=(
                f"Normalized replica '{self.replica_record_id}' v{self.replica_version} via "
                f"'{self.transformation_id}' v{self.transformation_version}: "
                f"{len(self.produced_canonical_refs)} canonical record(s), {rejections_count} rejection(s)."
            ),
        )
        return outcome

    def _append_normalize_trace(
        self,
        *,
        event_type: IpTraceEventType,
        status: TraceEventStatus,
        summary_message: str,
        error_details: TraceErrorDetails | None = None,
    ) -> None:
        self.add_trace_event(
            IpTraceEvent.create(
                tenant_id=self.tenant_id,
                trace_id=self.trace_id,
                correlation_id=self.correlation_id,
                event_type=event_type.value,
                stage=PipelineStage.NORMALIZE,
                status=status,
                summary_message=summary_message,
                error_details=error_details,
                extra_metadata={
                    "transformation_id": self.transformation_id,
                    "transformation_version": self.transformation_version,
                },
            )
        )


@dataclass(frozen=True)
class NormalizationRejectionEntry:
    """Audit record for a normalization or validation failure."""

    ID_PREFIX: ClassVar[str] = IpIdPrefix.NORMALIZATION_REJECTION.value

    id: str
    tenant_id: str
    replica_record_id: str
    stream: str
    transformation_id: str
    transformation_version: int
    reason_code: str
    field_path: str | None
    detail: str
    trace_id: str
    correlation_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        replica_record_id: str,
        stream: str,
        transformation_id: str,
        transformation_version: int,
        reason_code: str,
        detail: str,
        trace_id: str,
        field_path: str | None = None,
        correlation_id: str | None = None,
    ) -> NormalizationRejectionEntry:
        return cls(
            id=generate_id(cls.ID_PREFIX),
            tenant_id=tenant_id,
            replica_record_id=replica_record_id,
            stream=stream,
            transformation_id=transformation_id,
            transformation_version=transformation_version,
            reason_code=reason_code,
            field_path=field_path,
            detail=detail,
            trace_id=trace_id,
            correlation_id=correlation_id,
            created_at=datetime.now(UTC),
        )

    def build_rejection_trace(self, *, summary_message: str) -> TraceEvent:
        """Builds an L3 NORMALIZATION_REJECTED trace event for non-ledger (shadow) rejections."""
        return IpTraceEvent.create(
            tenant_id=self.tenant_id,
            trace_id=self.trace_id,
            correlation_id=self.correlation_id,
            event_type=IpTraceEventType.NORMALIZATION_REJECTED.value,
            stage=PipelineStage.NORMALIZE,
            status=TraceEventStatus.FAILED,
            summary_message=summary_message,
            error_details=TraceErrorDetails(reason=self.reason_code, detail=self.detail),
            extra_metadata={
                "transformation_id": self.transformation_id,
                "transformation_version": self.transformation_version,
            },
        )


@dataclass(frozen=True)
class FieldShadowDiff:
    """Strongly-typed diff between active and candidate shadow values for a single field."""

    field_name: str
    active_value: JsonValue
    shadow_value: JsonValue

    def to_json_dict(self) -> JsonDict:
        return {
            "active": self.active_value,
            "shadow": self.shadow_value,
        }


@dataclass(frozen=True)
class EntityShadowDiff:
    """Strongly-typed shadow diff for a canonical entity draft."""

    canonical_type: str
    source_id: str
    field_diffs: tuple[FieldShadowDiff, ...]

    @property
    def entity_key(self) -> str:
        return f"{self.canonical_type}:{self.source_id}"

    def to_json_dict(self) -> JsonDict:
        return {fd.field_name: fd.to_json_dict() for fd in self.field_diffs}


@dataclass(frozen=True)
class NormalizationShadowDiffEntry:
    """Record of candidate mapper differences in shadow mode."""

    ID_PREFIX: ClassVar[str] = IpIdPrefix.SHADOW_DIFF.value

    id: str
    tenant_id: str
    replica_record_id: str
    candidate_version: int
    diff_data: JsonDict
    trace_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        replica_record_id: str,
        candidate_version: int,
        diff_data: JsonDict,
        trace_id: str,
    ) -> NormalizationShadowDiffEntry:
        return cls(
            id=generate_id(cls.ID_PREFIX),
            tenant_id=tenant_id,
            replica_record_id=replica_record_id,
            candidate_version=candidate_version,
            diff_data=diff_data,
            trace_id=trace_id,
            created_at=datetime.now(UTC),
        )


@dataclass(frozen=True)
class PendingReferenceEntry:
    """Unresolved source reference waiting for target canonical record creation."""

    ID_PREFIX: ClassVar[str] = IpIdPrefix.PENDING_REFERENCE.value

    id: str
    tenant_id: str
    source_connection_id: str
    target_canonical_type: str
    target_source_id: str
    referencing_canonical_type: str
    referencing_source_id: str
    referencing_field: str
    status: PendingReferenceStatus = PendingReferenceStatus.PENDING
    trace_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        source_connection_id: str,
        target_canonical_type: str,
        target_source_id: str,
        referencing_canonical_type: str,
        referencing_source_id: str,
        referencing_field: str,
        trace_id: str,
    ) -> PendingReferenceEntry:
        return cls(
            id=generate_id(cls.ID_PREFIX),
            tenant_id=tenant_id,
            source_connection_id=source_connection_id,
            target_canonical_type=target_canonical_type,
            target_source_id=target_source_id,
            referencing_canonical_type=referencing_canonical_type,
            referencing_source_id=referencing_source_id,
            referencing_field=referencing_field,
            status=PendingReferenceStatus.PENDING,
            trace_id=trace_id,
            created_at=datetime.now(UTC),
            resolved_at=None,
        )
