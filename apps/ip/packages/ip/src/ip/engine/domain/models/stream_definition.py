"""Stream definition and extraction payload value objects for L2 Universal Replica layer."""

from __future__ import annotations

from dataclasses import dataclass, field

from seedwork.domain.types import JsonDict, JsonPrimitive

from ip.engine.domain.enums import CursorKind, RejectionReason, SyncMode


@dataclass(frozen=True)
class DeletionMarker:
    """Configuration indicating that a record represents a deletion in the source system."""

    field_path: tuple[str, ...]
    expected_value: JsonPrimitive


@dataclass(frozen=True)
class StreamDefinition:
    """Declarative stream specification stored with connection configuration."""

    stream: str
    record_path: tuple[str, ...] = ()
    primary_key: tuple[tuple[str, ...], ...] = ()
    cursor_field: tuple[str, ...] | None = None
    cursor_kind: CursorKind = CursorKind.STRING
    sync_mode: SyncMode = SyncMode.INCREMENTAL
    deletion_marker: DeletionMarker | None = None
    extractor_id: str = "declarative"


@dataclass(frozen=True)
class ExtractedRecord:
    """A single record extracted from an L1 payload, ready for replica merge."""

    primary_key_values: tuple[JsonPrimitive, ...]
    cursor_value: str | int | float | None
    data: JsonDict
    is_deleted: bool = False


@dataclass(frozen=True)
class ExtractionRejection:
    """Represents a record that could not be extracted due to missing primary key or malformed data."""

    reason: RejectionReason
    record_index: int
    detail: str


@dataclass(frozen=True)
class ExtractionBatch:
    """Result of running a RecordExtractor on a raw source payload."""

    records: tuple[ExtractedRecord, ...] = field(default_factory=tuple)
    rejections: tuple[ExtractionRejection, ...] = field(default_factory=tuple)
