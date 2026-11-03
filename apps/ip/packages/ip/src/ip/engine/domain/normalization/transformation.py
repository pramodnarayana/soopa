"""L3 Transformation aggregate root, canonical drafts, and transformer protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar, Protocol

from seedwork.domain.aggregate import AggregateRoot
from seedwork.domain.exceptions import Result
from seedwork.domain.types import JsonDict, JsonValue
from seedwork.utils import generate_id
from strace.domain import TraceEvent

from ip.engine.domain.constants import IpIdPrefix
from ip.engine.domain.exceptions import NormalizationFailedError
from ip.engine.domain.normalization.enums import (
    NormalizationOutcome,
    NormalizationRejectionReason,
    RuleSeverity,
    TransformationMode,
)
from ip.engine.domain.normalization.events import (
    TransformationChangedEvent,
    TransformationVersionPromotedEvent,
)
from ip.engine.domain.trace.enums import IpTraceEventType, PipelineStage, TraceEventStatus
from ip.engine.domain.trace.trace_event import IpTraceEvent

__all__ = [
    "CanonicalDataDict",
    "CanonicalDataValue",
    "CanonicalDraft",
    "CanonicalEntityDefinition",
    "DomainTransformerProtocol",
    "QualityRule",
    "ReplicaSnapshot",
    "SourceReference",
    "Transformation",
    "TransformationContext",
    "TransformationRejection",
    "TransformationResult",
]


CanonicalDataValue = JsonValue | Decimal


CanonicalDataDict = dict[str, CanonicalDataValue]


@dataclass(frozen=True)
class SourceReference:
    """Unresolved or resolved reference to an entity produced by the same or different stream."""

    field_name: str
    target_canonical_type: str
    target_source_id: str


@dataclass(frozen=True)
class CanonicalDraft:
    """Draft canonical record produced by a pure TransformerPort implementation."""

    canonical_type: str
    source_id: str
    fields: JsonDict
    references: tuple[SourceReference, ...] = ()
    extensions: JsonDict = field(default_factory=dict)


@dataclass(frozen=True)
class TransformationRejection:
    """Typed rejection produced by a transformer when a record violates business expectations."""

    reason: NormalizationRejectionReason | str
    field_path: str | None
    detail: str


@dataclass(frozen=True)
class TransformationResult:
    """Deterministic output of a transformer execution."""

    drafts: tuple[CanonicalDraft, ...] = ()
    rejections: tuple[TransformationRejection, ...] = ()


@dataclass(frozen=True)
class TransformationContext:
    """Pure contextual metadata passed into TransformerPort.transform()."""

    connection_id: str
    stream: str
    tenant_id: str
    trace_id: str
    correlation_id: str | None = None


@dataclass(frozen=True)
class ReplicaSnapshot:
    """Immutable view of an L2 replica snapshot provided as input to transformers."""

    id: str
    connection_id: str
    stream: str
    record_key: str
    version: int
    data: JsonDict
    is_deleted: bool = False


class QualityRule(Protocol):
    """Protocol for pure business and data quality validation rules."""

    @property
    def code(self) -> str: ...

    @property
    def severity(self) -> RuleSeverity: ...

    def evaluate(self, fields: JsonDict) -> str | None: ...


@dataclass(frozen=True)
class CanonicalEntityDefinition:
    """Canonical entity specification owned by domain packages."""

    canonical_type: str
    schema_version: int = 1
    quality_rules: tuple[QualityRule, ...] = ()


@dataclass(kw_only=True)
class Transformation(AggregateRoot):
    """Control plane configuration binding a connection stream to an active transformer version."""

    ID_PREFIX: ClassVar[str] = IpIdPrefix.TRANSFORMATION.value

    id: str
    tenant_id: str
    connection_id: str
    stream: str
    transformation_id: str
    transformation_version: int
    mode: TransformationMode = TransformationMode.ACTIVE
    shadow_transformation_version: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        connection_id: str,
        stream: str,
        transformation_id: str,
        transformation_version: int,
        mode: TransformationMode = TransformationMode.ACTIVE,
        shadow_transformation_version: int | None = None,
    ) -> Transformation:
        now = datetime.now(UTC)
        return cls(
            id=generate_id(cls.ID_PREFIX),
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream=stream,
            transformation_id=transformation_id,
            transformation_version=transformation_version,
            mode=mode,
            shadow_transformation_version=shadow_transformation_version,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def bind(
        cls,
        *,
        tenant_id: str,
        connection_id: str,
        stream: str,
        transformation_id: str,
        transformation_version: int,
        mode: TransformationMode = TransformationMode.ACTIVE,
        shadow_transformation_version: int | None = None,
    ) -> Transformation:
        """Creates a new stream Transformation binding and records TransformationChangedEvent."""
        transformation = cls.create(
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream=stream,
            transformation_id=transformation_id,
            transformation_version=transformation_version,
            mode=mode,
            shadow_transformation_version=shadow_transformation_version,
        )
        transformation._record_changed_event()
        return transformation

    def rebind(
        self,
        *,
        transformation_id: str,
        transformation_version: int,
        mode: TransformationMode,
        shadow_transformation_version: int | None = None,
    ) -> Transformation:
        """Updates an existing stream Transformation binding and records TransformationChangedEvent."""
        self.transformation_id = transformation_id
        self.transformation_version = transformation_version
        self.mode = mode
        self.shadow_transformation_version = shadow_transformation_version
        self.updated_at = datetime.now(UTC)
        self._record_changed_event()
        return self

    def promote_shadow_version(
        self,
    ) -> Result[tuple[int, int], NormalizationFailedError]:
        """Promotes shadow_transformation_version to active transformation_version."""
        if self.shadow_transformation_version is None:
            return Result.fail(
                NormalizationFailedError.with_message(
                    f"No candidate shadow_transformation_version configured on transformation '{self.id}' to promote."
                )
            )
        previous_version = self.transformation_version
        promoted_version = self.shadow_transformation_version
        self.transformation_version = promoted_version
        self.mode = TransformationMode.ACTIVE
        self.shadow_transformation_version = None
        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            TransformationVersionPromotedEvent(
                id=self.id,
                tenant_id=self.tenant_id,
                connection_id=self.connection_id,
                stream=self.stream,
                transformation_id=self.transformation_id,
                promoted_version=promoted_version,
                previous_version=previous_version,
            )
        )
        return Result.ok((previous_version, promoted_version))

    def _record_changed_event(self) -> None:
        self.add_domain_event(
            TransformationChangedEvent(
                id=self.id,
                tenant_id=self.tenant_id,
                connection_id=self.connection_id,
                stream=self.stream,
                transformation_id=self.transformation_id,
                transformation_version=self.transformation_version,
                mode=self.mode.value,
                shadow_transformation_version=self.shadow_transformation_version,
            )
        )

    def build_skipped_stale_trace(
        self,
        *,
        replica_version: int,
        trace_id: str,
        correlation_id: str | None = None,
    ) -> TraceEvent:
        """Builds an L3 NORMALIZE trace event when an out-of-order stale replica version is skipped."""
        return IpTraceEvent.create(
            tenant_id=self.tenant_id,
            trace_id=trace_id,
            correlation_id=correlation_id,
            event_type=IpTraceEventType.SKIPPED_STALE.value,
            stage=PipelineStage.NORMALIZE,
            status=TraceEventStatus.SUCCESS,
            summary_message=(
                f"Skipped stale replica version {replica_version} "
                f"for transformer '{self.transformation_id}' v{self.transformation_version}."
            ),
            extra_metadata={
                "transformation_id": self.transformation_id,
                "transformation_version": self.transformation_version,
            },
        )

    def build_shadow_evaluation_trace(
        self,
        *,
        replica_record_id: str,
        candidate_version: int,
        drafts_count: int,
        shadow_diff_count: int,
        outcome: NormalizationOutcome,
        trace_id: str,
        correlation_id: str | None = None,
    ) -> TraceEvent:
        """Builds an L3 NORMALIZE trace event for a shadow-only candidate evaluation."""
        is_normalized = outcome == NormalizationOutcome.NORMALIZED
        return IpTraceEvent.create(
            tenant_id=self.tenant_id,
            trace_id=trace_id,
            correlation_id=correlation_id,
            event_type=(
                IpTraceEventType.NORMALIZED.value
                if is_normalized
                else IpTraceEventType.NORMALIZATION_REJECTED.value
            ),
            stage=PipelineStage.NORMALIZE,
            status=TraceEventStatus.SUCCESS if is_normalized else TraceEventStatus.FAILED,
            summary_message=(
                f"Shadow-evaluated replica '{replica_record_id}' via "
                f"'{self.transformation_id}' v{candidate_version}: "
                f"{drafts_count} draft(s), {shadow_diff_count} diff(s)."
            ),
            extra_metadata={
                "transformation_id": self.transformation_id,
                "transformation_version": self.transformation_version,
            },
        )


class DomainTransformerProtocol(Protocol):
    """Pure domain protocol for deterministic Layer 3 normalization transformers."""

    @property
    def transformation_id(self) -> str: ...

    @property
    def transformation_version(self) -> int: ...

    @property
    def target_types(self) -> tuple[str, ...]: ...

    def transform(
        self, replica: ReplicaSnapshot, context: TransformationContext
    ) -> TransformationResult: ...
