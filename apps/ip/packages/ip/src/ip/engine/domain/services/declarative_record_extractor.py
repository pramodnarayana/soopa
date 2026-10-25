"""Declarative pure RecordExtractor implementation for L2 Universal Replica layer."""

from __future__ import annotations

from ip.engine.domain.enums import CursorKind, RejectionReason
from ip.engine.domain.models.stream_definition import (
    ExtractedRecord,
    ExtractionBatch,
    ExtractionRejection,
    StreamDefinition,
)
from seedwork.domain.types import JsonDict, JsonPrimitive, JsonValue


def _extract_path(data: JsonValue, path: tuple[str, ...]) -> JsonValue:
    """Navigates a nested dict structure along the given path."""
    curr: JsonValue = data
    for key in path:
        if not isinstance(curr, dict) or key not in curr:
            return None
        curr = curr[key]
    return curr


def _resolve_target_list(
    raw: JsonValue, record_path: tuple[str, ...]
) -> tuple[list[JsonValue] | None, ExtractionRejection | None]:
    """Navigates to the records array in the raw payload."""
    target: JsonValue = raw
    if record_path:
        for step in record_path:
            if isinstance(target, dict) and step in target:
                target = target[step]
            else:
                return None, ExtractionRejection(
                    reason=RejectionReason.EXTRACTION_FAILED,
                    record_index=0,
                    detail=f"Record path '{'.'.join(record_path)}' could not be resolved in payload.",
                )

    if isinstance(target, list):
        return target, None
    if isinstance(target, dict):
        return [target], None
    if target is None:
        return [], None

    return None, ExtractionRejection(
        reason=RejectionReason.NOT_AN_OBJECT,
        record_index=0,
        detail=f"Target payload at record path is neither a list nor a dict, got {type(target).__name__}.",
    )


def _extract_primary_keys(
    item: JsonDict,
    pk_paths: tuple[tuple[str, ...], ...],
) -> tuple[tuple[JsonPrimitive, ...] | None, ExtractionRejection | None]:
    """Extracts primary key values or falls back to standard id."""
    pk_values: list[JsonPrimitive] = []
    for pk_path in pk_paths:
        val = _extract_path(item, pk_path)
        if val is None or val == "":
            return None, ExtractionRejection(
                reason=RejectionReason.MISSING_PRIMARY_KEY,
                record_index=0,
                detail=f"Record missing primary key at path '{'.'.join(pk_path)}'.",
            )
        if isinstance(val, (str, int, float, bool)):
            pk_values.append(val)
        else:
            pk_values.append(str(val))

    if not pk_values:
        fallback_id = item.get("id") or item.get("_id")
        if fallback_id is not None and fallback_id != "":
            if isinstance(fallback_id, (str, int, float, bool)):
                pk_values = [fallback_id]
            else:
                pk_values = [str(fallback_id)]
        else:
            return None, ExtractionRejection(
                reason=RejectionReason.EMPTY_PRIMARY_KEY,
                record_index=0,
                detail="StreamDefinition specifies no primary_key paths and fallback 'id' was missing.",
            )

    return tuple(pk_values), None


def _extract_cursor_value(
    item: JsonDict,
    cursor_field: tuple[str, ...] | None,
    cursor_kind: CursorKind,
) -> tuple[str | int | float | None, ExtractionRejection | None]:
    """Extracts and validates cursor value according to cursor_kind."""
    if not cursor_field:
        return None, None

    raw_cursor = _extract_path(item, cursor_field)
    if raw_cursor is None:
        return None, None

    if cursor_kind == CursorKind.INTEGER:
        if isinstance(raw_cursor, (int, float, str, bytes)):
            try:
                return int(raw_cursor), None
            except (ValueError, TypeError):
                pass
        return None, ExtractionRejection(
            reason=RejectionReason.INVALID_CURSOR,
            record_index=0,
            detail=f"Cursor value '{raw_cursor}' cannot be parsed as INTEGER.",
        )

    return str(raw_cursor), None


def _extract_single_record(
    item: JsonValue,
    idx: int,
    stream: StreamDefinition,
) -> tuple[ExtractedRecord | None, ExtractionRejection | None]:
    """Extracts a single record or rejection from an item in the records array."""
    if not isinstance(item, dict):
        return None, ExtractionRejection(
            reason=RejectionReason.NOT_AN_OBJECT,
            record_index=idx,
            detail=f"Record at index {idx} is not a JSON object (got {type(item).__name__}).",
        )

    pk_values, pk_rejection = _extract_primary_keys(item, stream.primary_key)
    if pk_rejection is not None:
        return None, ExtractionRejection(
            reason=pk_rejection.reason,
            record_index=idx,
            detail=pk_rejection.detail,
        )

    cursor_val, cursor_rejection = _extract_cursor_value(
        item, stream.cursor_field, stream.cursor_kind
    )
    if cursor_rejection is not None:
        return None, ExtractionRejection(
            reason=cursor_rejection.reason,
            record_index=idx,
            detail=cursor_rejection.detail,
        )

    is_deleted = False
    if stream.deletion_marker is not None:
        marker_val = _extract_path(item, stream.deletion_marker.field_path)
        if marker_val == stream.deletion_marker.expected_value:
            is_deleted = True

    assert pk_values is not None
    return (
        ExtractedRecord(
            primary_key_values=pk_values,
            cursor_value=cursor_val,
            data=item,
            is_deleted=is_deleted,
        ),
        None,
    )


class DeclarativeRecordExtractor:
    """Pure declarative extractor resolving records from JSON payloads using stream configuration."""

    def extract(self, raw: JsonValue, stream: StreamDefinition) -> ExtractionBatch:
        raw_list, rejection = _resolve_target_list(raw, stream.record_path)
        if rejection is not None:
            return ExtractionBatch(records=(), rejections=(rejection,))
        if not raw_list:
            return ExtractionBatch(records=(), rejections=())

        records: list[ExtractedRecord] = []
        rejections: list[ExtractionRejection] = []

        for idx, item in enumerate(raw_list):
            record, rej = _extract_single_record(item, idx, stream)
            if rej is not None:
                rejections.append(rej)
            elif record is not None:
                records.append(record)

        return ExtractionBatch(records=tuple(records), rejections=tuple(rejections))
