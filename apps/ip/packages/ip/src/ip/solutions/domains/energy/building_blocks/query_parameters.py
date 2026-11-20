"""Reusable query parameter formatters for Energy domain endpoints."""

from __future__ import annotations

from collections.abc import Mapping

from seedwork.domain.types import JsonPrimitive


def build_query_params(params: Mapping[str, JsonPrimitive]) -> dict[str, str]:
    """Filters None values and formats primitives into query parameter strings."""
    result: dict[str, str] = {}
    for key, val in params.items():
        if val is not None:
            result[key] = str(val).lower() if isinstance(val, bool) else str(val)
    return result


def build_pagination_params(page: int, page_size: int) -> dict[str, str]:
    """Builds standard limit/offset pagination query parameters."""
    return {
        "page": str(page),
        "limit": str(page_size),
        "offset": str((page - 1) * page_size),
    }
