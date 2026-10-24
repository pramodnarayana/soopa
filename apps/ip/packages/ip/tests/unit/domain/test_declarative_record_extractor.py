"""Unit tests for DeclarativeRecordExtractor (pure domain service)."""

from __future__ import annotations

from ip.engine.domain.enums import CursorKind, RejectionReason
from ip.engine.domain.models.stream_definition import DeletionMarker, StreamDefinition
from ip.engine.domain.services.declarative_record_extractor import DeclarativeRecordExtractor


def test_extractor_extracts_from_nested_record_path() -> None:
    extractor = DeclarativeRecordExtractor()
    stream = StreamDefinition(
        stream="meters",
        primary_key=(("serial",),),
        record_path=("response", "items"),
    )
    payload = {
        "response": {
            "items": [
                {"serial": "MTR-01", "reading": 100},
                {"serial": "MTR-02", "reading": 200},
            ]
        }
    }

    batch = extractor.extract(payload, stream)
    assert len(batch.rejections) == 0
    assert len(batch.records) == 2
    assert batch.records[0].primary_key_values == ("MTR-01",)
    assert batch.records[0].data["reading"] == 100
    assert batch.records[1].primary_key_values == ("MTR-02",)


def test_extractor_returns_rejection_when_record_path_not_found() -> None:
    extractor = DeclarativeRecordExtractor()
    stream = StreamDefinition(
        stream="meters",
        primary_key=(("id",),),
        record_path=("data", "results"),
    )
    payload = {"error": "not found"}

    batch = extractor.extract(payload, stream)
    assert len(batch.records) == 0
    assert len(batch.rejections) == 1
    assert batch.rejections[0].reason == RejectionReason.EXTRACTION_FAILED


def test_extractor_handles_composite_primary_key() -> None:
    extractor = DeclarativeRecordExtractor()
    stream = StreamDefinition(
        stream="device_events",
        primary_key=(("org", "code"), ("device_id",)),
    )
    payload = [
        {"org": {"code": "ACME"}, "device_id": "DEV-99", "temp": 72.5},
    ]

    batch = extractor.extract(payload, stream)
    assert len(batch.rejections) == 0
    assert len(batch.records) == 1
    assert batch.records[0].primary_key_values == ("ACME", "DEV-99")


def test_extractor_rejection_for_missing_primary_key() -> None:
    extractor = DeclarativeRecordExtractor()
    stream = StreamDefinition(
        stream="users",
        primary_key=(("user_id",),),
    )
    payload = [
        {"user_id": "usr_1", "name": "Alice"},
        {"name": "Bob"},  # Missing primary key
    ]

    batch = extractor.extract(payload, stream)
    assert len(batch.records) == 1
    assert batch.records[0].primary_key_values == ("usr_1",)
    assert len(batch.rejections) == 1
    assert batch.rejections[0].record_index == 1
    assert batch.rejections[0].reason == RejectionReason.MISSING_PRIMARY_KEY


def test_extractor_rejection_for_non_object_item() -> None:
    extractor = DeclarativeRecordExtractor()
    stream = StreamDefinition(
        stream="items",
        primary_key=(("id",),),
    )
    payload = [
        {"id": "1"},
        "invalid_string_item",
    ]

    batch = extractor.extract(payload, stream)
    assert len(batch.records) == 1
    assert len(batch.rejections) == 1
    assert batch.rejections[0].record_index == 1
    assert batch.rejections[0].reason == RejectionReason.NOT_AN_OBJECT


def test_extractor_cursor_extraction_and_integer_validation() -> None:
    extractor = DeclarativeRecordExtractor()
    stream = StreamDefinition(
        stream="readings",
        primary_key=(("id",),),
        cursor_field=("seq",),
        cursor_kind=CursorKind.INTEGER,
    )
    payload = [
        {"id": "r1", "seq": 105},
        {"id": "r2", "seq": "not-an-integer"},
    ]

    batch = extractor.extract(payload, stream)
    assert len(batch.records) == 1
    assert batch.records[0].cursor_value == 105
    assert len(batch.rejections) == 1
    assert batch.rejections[0].record_index == 1
    assert batch.rejections[0].reason == RejectionReason.INVALID_CURSOR


def test_extractor_deletion_marker_detection() -> None:
    extractor = DeclarativeRecordExtractor()
    stream = StreamDefinition(
        stream="customers",
        primary_key=(("id",),),
        deletion_marker=DeletionMarker(
            field_path=("meta", "status"),
            expected_value="ARCHIVED",
        ),
    )
    payload = [
        {"id": "c1", "meta": {"status": "ACTIVE"}},
        {"id": "c2", "meta": {"status": "ARCHIVED"}},
    ]

    batch = extractor.extract(payload, stream)
    assert len(batch.rejections) == 0
    assert len(batch.records) == 2
    assert batch.records[0].is_deleted is False
    assert batch.records[1].is_deleted is True
