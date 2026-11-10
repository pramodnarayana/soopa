"""
Causal Database Replication Watermark Codec (`replication_watermark`).

Provides monotonic 64-bit `ReplicationWatermark` encoding and decoding for
deterministic causal Read-Your-Own-Writes (RYOW) routing and cache fencing.
"""

from __future__ import annotations

import re
from typing import Final

from database.types import ReplicationWatermark

_PG_LSN_PATTERN: Final[re.Pattern[str]] = re.compile(r"^([0-9A-Fa-f]{1,8})/([0-9A-Fa-f]{1,8})$")
_MAX_UINT64: Final[int] = 0xFFFFFFFFFFFFFFFF
_LOW32_MASK: Final[int] = 0xFFFFFFFF


def parse_postgres_lsn(lsn_str: str) -> ReplicationWatermark:
    """Parse a PostgreSQL `HIGH/LOW` hex WAL LSN string into a 64-bit `ReplicationWatermark`."""
    stripped = lsn_str.strip()
    match = _PG_LSN_PATTERN.match(stripped)
    if match is None:
        raise ValueError(f"Invalid replication watermark LSN format: '{lsn_str}'")

    high_32 = int(match.group(1), 16)
    low_32 = int(match.group(2), 16)
    return ReplicationWatermark((high_32 << 32) | low_32)


def format_postgres_lsn(watermark: ReplicationWatermark) -> str:
    """Format a 64-bit `ReplicationWatermark` back into canonical `HIGH/LOW` uppercase hex."""
    raw = int(watermark)
    if raw < 0 or raw > _MAX_UINT64:
        raise ValueError(f"ReplicationWatermark out of 64-bit unsigned range: {raw}")

    high_32 = raw >> 32
    low_32 = raw & _LOW32_MASK
    return f"{high_32:X}/{low_32:X}"


def max_watermark(
    first: ReplicationWatermark,
    second: ReplicationWatermark,
) -> ReplicationWatermark:
    """Return the higher of two monotonic `ReplicationWatermark` values."""
    return first if first >= second else second


__all__ = ["format_postgres_lsn", "max_watermark", "parse_postgres_lsn"]
