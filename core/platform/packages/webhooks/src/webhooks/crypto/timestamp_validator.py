"""Centralized timestamp drift and replay attack prevention utilities."""

from __future__ import annotations

import time


def validate_timestamp(
    timestamp_val: str | int | float,
    tolerance_seconds: int = 300,
    current_time: float | None = None,
) -> bool:
    """Validates that a unix timestamp is within `tolerance_seconds` of the current time.

    Protects against replay attacks by rejecting old or future-dated webhook timestamps.
    """
    try:
        ts = float(timestamp_val)
    except (ValueError, TypeError):
        return False

    now = time.time() if current_time is None else current_time
    diff = abs(now - ts)
    return diff <= float(tolerance_seconds)
