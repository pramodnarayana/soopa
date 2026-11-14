"""Multiplexed event discriminator resolution across all 3 tiers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

HEADER_CANDIDATES: Final[tuple[str, ...]] = (
    "x-event-type",
    "x-action",
    "x-command",
    "ce-type",
)

BODY_CANDIDATES: Final[tuple[str, ...]] = (
    "event_type",
    "action",
    "type",
    "command",
    "msg_type",
)

QUERY_CANDIDATES: Final[tuple[str, ...]] = (
    "event",
    "action",
    "event_type",
    "type",
)


def resolve_event_discriminator(
    headers: Mapping[str, str],
    parsed_body: Mapping[str, object] | None,
    query_params: Mapping[str, str],
) -> str | None:
    """Evaluates Tier 1 -> Tier 2 -> Tier 3 discrimination in sub-millisecond time.

    Returns the identified event discriminator string, or None if fallback to wildcard ('*') is needed.
    """
    # Normalize headers for case-insensitive lookup
    normalized_headers: dict[str, str] = {
        k.strip().lower(): str(v).strip() for k, v in headers.items()
    }

    # 1. Tier 1: Fast header check (O(1) dictionary lookup)
    for header in HEADER_CANDIDATES:
        if (val := normalized_headers.get(header)) and val:
            return val

    # 2. Tier 2: Body JSON attribute check
    if parsed_body and isinstance(parsed_body, Mapping):
        for field in BODY_CANDIDATES:
            raw_val = parsed_body.get(field)
            if isinstance(raw_val, str) and raw_val.strip():
                return raw_val.strip()

    # 3. Tier 3: Query parameter fallback
    normalized_query: dict[str, str] = {
        k.strip().lower(): str(v).strip() for k, v in query_params.items()
    }
    for param in QUERY_CANDIDATES:
        if (val := normalized_query.get(param)) and val:
            return val

    # 4. Fallback: None (caller matches wildcard route '*')
    return None
