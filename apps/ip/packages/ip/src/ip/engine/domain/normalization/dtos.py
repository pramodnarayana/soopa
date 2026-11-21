"""L3 Normalization Domain Value Objects and Contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from seedwork.domain.types import JsonDict, JsonValue

from ip.engine.domain.normalization.enums import NormalizationRejectionReason

if TYPE_CHECKING:
    from ip.engine.domain.normalization.protocols import QualityRule

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


@dataclass(frozen=True)
class CanonicalEntityDefinition:
    """Canonical entity specification owned by domain packages."""

    canonical_type: str
    schema_version: int = 1
    quality_rules: tuple[QualityRule, ...] = ()


__all__ = [
    "CanonicalDataDict",
    "CanonicalDataValue",
    "CanonicalDraft",
    "CanonicalEntityDefinition",
    "ReplicaSnapshot",
    "SourceReference",
    "TransformationContext",
    "TransformationRejection",
    "TransformationResult",
]
