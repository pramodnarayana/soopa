"""Pure numeric validation and coercion utilities shared across IP vertical solution domains."""

from __future__ import annotations

import math


def is_non_finite_number(val: object) -> bool:
    """Returns True when `val` is a non-finite float/int (`NaN`, `+-Inf`, float overflow) or numeric string."""
    if val is None or isinstance(val, bool):
        return False
    if isinstance(val, (int, float)):
        try:
            return not math.isfinite(float(val))
        except OverflowError:
            return True
    if isinstance(val, str) and val.strip():
        try:
            parsed = float(val.strip())
        except ValueError:
            return False
        except OverflowError:
            return True
        return not math.isfinite(parsed)
    return False


def to_optional_finite_float(val: object) -> float | None:
    """Coerces `val` to a finite `float`, returning `None` for booleans, invalid strings, or non-finite/overflowing values."""
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        try:
            parsed = float(val)
        except OverflowError:
            return None
        return parsed if math.isfinite(parsed) else None
    if isinstance(val, str) and val.strip():
        try:
            parsed = float(val.strip())
        except (ValueError, OverflowError):
            return None
        return parsed if math.isfinite(parsed) else None
    return None


def to_finite_float(val: object, default: float = 0.0) -> float:
    """Coerces `val` to a finite `float`, falling back to `default` when absent, invalid, or non-finite."""
    parsed = to_optional_finite_float(val)
    return default if parsed is None else parsed


def to_finite_int(val: object, default: int = 0) -> int:
    """Coerces `val` to an `int`, falling back to `default` for booleans, invalid strings, or non-finite floats."""
    if val is None or isinstance(val, bool):
        return default
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val) if math.isfinite(val) else default
    if isinstance(val, str) and val.strip():
        try:
            return int(val.strip())
        except (ValueError, OverflowError):
            return default
    return default


__all__ = [
    "is_non_finite_number",
    "to_finite_float",
    "to_finite_int",
    "to_optional_finite_float",
]
