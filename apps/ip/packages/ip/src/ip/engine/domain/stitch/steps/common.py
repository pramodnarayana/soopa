"""Common helper utilities for Stitch Step DTOs."""

from __future__ import annotations

from seedwork.domain.types import JsonDict


def resolve_effective_payload(data: JsonDict) -> JsonDict:
    """Extracts effective step input, merging parent task output if nested under parents."""
    parents = data.get("parents")
    if isinstance(parents, dict):
        for parent_val in parents.values():
            if isinstance(parent_val, dict) and (
                "connection_id" in parent_val
                or "destination_connection_id" in parent_val
                or "target_connection_id" in parent_val
            ):
                return {**data, **parent_val}
    return dict(data)


__all__ = ["resolve_effective_payload"]
