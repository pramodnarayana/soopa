"""Unit tests for atomic field transform building blocks."""

from datetime import UTC
from enum import Enum

import pytest
from ip.sdk.transforms import map_enum, parse_iso_datetime, safe_float, safe_int


class DeviceStatus(Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    MAINTENANCE = "MAINTENANCE"


def test_parse_iso_datetime_parses_iso_string() -> None:
    dt = parse_iso_datetime("2026-10-01T12:30:00+00:00")
    assert dt.year == 2026
    assert dt.month == 10
    assert dt.day == 1
    assert dt.hour == 12
    assert dt.minute == 30
    assert dt.tzinfo is not None


def test_parse_iso_datetime_parses_numeric_timestamp() -> None:
    dt = parse_iso_datetime(1700000000)
    assert dt.tzinfo == UTC


def test_parse_iso_datetime_rejects_empty_string() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        parse_iso_datetime("   ")


def test_parse_iso_datetime_rejects_none() -> None:
    with pytest.raises(ValueError, match="cannot be None"):
        parse_iso_datetime(None)


def test_safe_float_parses_numeric_string() -> None:
    assert safe_float("42.5") == 42.5
    assert safe_float(100) == 100.0


def test_safe_float_returns_default_for_invalid_string() -> None:
    assert safe_float("invalid_number", default=-1.0) == -1.0


def test_safe_float_handles_boolean_values() -> None:
    assert safe_float(True) == 1.0
    assert safe_float(False) == 0.0


def test_safe_int_parses_float_string() -> None:
    assert safe_int("99.9") == 99
    assert safe_int(123) == 123


def test_safe_int_returns_default_for_none() -> None:
    assert safe_int(None, default=7) == 7


def test_map_enum_resolves_matching_key_case_insensitively() -> None:
    mapping = {
        "ONLINE": DeviceStatus.ONLINE,
        "OFFLINE": DeviceStatus.OFFLINE,
    }
    assert map_enum("online", mapping, DeviceStatus.OFFLINE) == DeviceStatus.ONLINE
    assert map_enum("ONLINE", mapping, DeviceStatus.OFFLINE) == DeviceStatus.ONLINE


def test_map_enum_returns_default_for_unknown_key() -> None:
    mapping = {"ONLINE": DeviceStatus.ONLINE}
    assert map_enum("UNKNOWN_STATE", mapping, DeviceStatus.MAINTENANCE) == DeviceStatus.MAINTENANCE
    assert map_enum(None, mapping, DeviceStatus.MAINTENANCE) == DeviceStatus.MAINTENANCE
