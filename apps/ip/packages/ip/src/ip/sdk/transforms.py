"""Reusable atomic field transformation building blocks for solution normalizers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timezone
from typing import TypeVar

from seedwork.domain.types import JsonValue

_T = TypeVar("_T")


def parse_iso_datetime(value: JsonValue, default_tz: timezone = UTC) -> datetime:
    """Safely parse an ISO-8601 string or numeric timestamp into a timezone-aware datetime."""
    if value is None:
        raise ValueError("Timestamp value cannot be None")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=default_tz)
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Timestamp string cannot be empty")
        dt = datetime.fromisoformat(cleaned)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=default_tz)
    raise ValueError(f"Unsupported timestamp type: {type(value)}")


def safe_float(value: JsonValue, default: float = 0.0) -> float:
    """Safely convert a JsonValue to float without raising exceptions."""
    if value is None:
        return default
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def safe_int(value: JsonValue, default: int = 0) -> int:
    """Safely convert a JsonValue to int without raising exceptions."""
    if value is None:
        return default
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except ValueError:
            return default
    return default


def map_enum(value: JsonValue, mapping: Mapping[str, _T], default: _T) -> _T:
    """Map a string/value to an enum value using a case-insensitive lookup table."""
    if not isinstance(value, str):
        return default
    key = value.strip().upper()
    return mapping.get(key, default)
