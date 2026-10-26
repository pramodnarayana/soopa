"""L3 Normalization domain models, value objects, and rule definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar, Protocol

from seedwork.domain.types import JsonDict, JsonValue
from seedwork.id_registry import DomainIdPrefix
from seedwork.models import AggregateRoot
from seedwork.utils import generate_id

from ip.engine.domain.enums import (
    MappingMode,
    NormalizationOutcome,
    NormalizationRejectionReason,
    PendingReferenceStatus,
    RuleSeverity,
)


@dataclass(frozen=True)
class SourceReference:
    """Unresolved or resolved reference to an entity produced by the same or different stream."""

    field_name: str
    target_canonical_type: str
    target_source_id: str


@dataclass(frozen=True)
class CanonicalDraft:
    """Draft canonical record produced by a pure MapperPort implementation."""

    canonical_type: str
    source_id: str
    fields: JsonDict
    references: tuple[SourceReference, ...] = ()
    extensions: JsonDict = field(default_factory=dict)


@dataclass(frozen=True)
class MappingRejection:
    """Typed rejection produced by a mapper when a record violates business expectations."""

    reason: NormalizationRejectionReason | str
    field_path: str | None
    detail: str


@dataclass(frozen=True)
class MappingResult:
    """Deterministic output of a mapper execution."""

    drafts: tuple[CanonicalDraft, ...] = ()
    rejections: tuple[MappingRejection, ...] = ()


@dataclass(frozen=True)
class MappingContext:
    """Pure contextual metadata passed into MapperPort.map()."""

    connection_id: str
    stream: str
    tenant_id: str
    trace_id: str
    correlation_id: str | None = None


@dataclass(frozen=True)
class ReplicaSnapshot:
    """Immutable view of an L2 replica snapshot provided as input to mappers."""

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
    def code(self) -> str:
        """Machine-readable quality rule code."""
        ...

    @property
    def severity(self) -> RuleSeverity:
        """REJECT drops the draft and records a rejection; FLAG marks quality_flag."""
        ...

    def evaluate(self, fields: JsonDict) -> str | None:
        """Evaluate fields. Returns failure message string if rule fails, or None if valid."""
        ...


@dataclass(frozen=True)
class CanonicalEntityDefinition:
    """Canonical entity specification owned by domain packages."""

    canonical_type: str
    schema_version: int = 1
    quality_rules: tuple[QualityRule, ...] = ()


@dataclass(kw_only=True)
class MappingBinding(AggregateRoot):
    """Control plane configuration binding a connection stream to an active mapper version."""

    ID_PREFIX: ClassVar[str] = DomainIdPrefix.IP_MAPPING_BINDING.value

    id: str
    tenant_id: str
    connection_id: str
    stream: str
    mapping_id: str
    mapping_version: int
    mode: MappingMode = MappingMode.ACTIVE
    shadow_mapping_version: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        connection_id: str,
        stream: str,
        mapping_id: str,
        mapping_version: int,
        mode: MappingMode = MappingMode.ACTIVE,
        shadow_mapping_version: int | None = None,
    ) -> MappingBinding:
        now = datetime.now(UTC)
        return cls(
            id=generate_id(cls.ID_PREFIX),
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream=stream,
            mapping_id=mapping_id,
            mapping_version=mapping_version,
            mode=mode,
            shadow_mapping_version=shadow_mapping_version,
            created_at=now,
            updated_at=now,
        )


@dataclass(frozen=True)
class NormalizationLedgerEntry:
    """Audit ledger entry tracking replica version to produced canonical references."""

    ID_PREFIX: ClassVar[str] = DomainIdPrefix.IP_NORMALIZATION_LEDGER.value

    id: str
    tenant_id: str
    replica_record_id: str
    replica_version: int
    mapping_id: str
    mapping_version: int
    produced_canonical_refs: tuple[tuple[str, str], ...]
    outcome: NormalizationOutcome
    trace_id: str
    correlation_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        replica_record_id: str,
        replica_version: int,
        mapping_id: str,
        mapping_version: int,
        produced_canonical_refs: tuple[tuple[str, str], ...],
        outcome: NormalizationOutcome,
        trace_id: str,
        correlation_id: str | None = None,
    ) -> NormalizationLedgerEntry:
        return cls(
            id=generate_id(cls.ID_PREFIX),
            tenant_id=tenant_id,
            replica_record_id=replica_record_id,
            replica_version=replica_version,
            mapping_id=mapping_id,
            mapping_version=mapping_version,
            produced_canonical_refs=produced_canonical_refs,
            outcome=outcome,
            trace_id=trace_id,
            correlation_id=correlation_id,
            created_at=datetime.now(UTC),
        )


@dataclass(frozen=True)
class NormalizationRejectionEntry:
    """Audit record for a normalization or validation failure."""

    ID_PREFIX: ClassVar[str] = DomainIdPrefix.IP_NORMALIZATION_REJECTION.value

    id: str
    tenant_id: str
    replica_record_id: str
    stream: str
    mapping_id: str
    mapping_version: int
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
        mapping_id: str,
        mapping_version: int,
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
            mapping_id=mapping_id,
            mapping_version=mapping_version,
            reason_code=reason_code,
            field_path=field_path,
            detail=detail,
            trace_id=trace_id,
            correlation_id=correlation_id,
            created_at=datetime.now(UTC),
        )


@dataclass(frozen=True)
class FieldShadowDiff:
    """Strongly-typed diff between active and candidate shadow values for a single field."""

    field_name: str
    active_value: JsonValue
    shadow_value: JsonValue

    def to_json_dict(self) -> JsonDict:
        """Serialize field diff for JSONB persistence."""
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
        """Composite key '<canonical_type>:<source_id>'."""
        return f"{self.canonical_type}:{self.source_id}"

    def to_json_dict(self) -> JsonDict:
        """Serialize entity field diffs for JSONB persistence."""
        return {fd.field_name: fd.to_json_dict() for fd in self.field_diffs}


@dataclass(frozen=True)
class NormalizationShadowDiffEntry:
    """Record of candidate mapper differences in shadow mode."""

    ID_PREFIX: ClassVar[str] = DomainIdPrefix.IP_SHADOW_DIFF.value

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

    ID_PREFIX: ClassVar[str] = DomainIdPrefix.IP_PENDING_REFERENCE.value

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


class DomainMapperProtocol(Protocol):
    """Pure domain protocol for deterministic Layer 3 normalization mappers."""

    @property
    def mapping_id(self) -> str:
        """Stable identifier for this mapper (e.g. 'domain.stream_mapper')."""
        ...

    @property
    def mapping_version(self) -> int:
        """Monotonic schema/logic version of this mapper."""
        ...

    @property
    def target_types(self) -> tuple[str, ...]:
        """Canonical entity types this mapper can produce."""
        ...

    def map(self, replica: ReplicaSnapshot, context: MappingContext) -> MappingResult:
        """Transform a replica snapshot into canonical drafts and/or rejections."""
        ...
