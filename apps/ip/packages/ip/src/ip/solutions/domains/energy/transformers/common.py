"""Common pure validation and conversion utilities for Energy domain transformers."""

from __future__ import annotations

from datetime import datetime


def is_valid_iso_timestamp(val: str) -> bool:
    """Validate whether the given string is a valid ISO-8601 timestamp."""
    try:
        datetime.fromisoformat(val.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True
