from enum import StrEnum
from typing import Final

MAX_PG_IDENTIFIER_LENGTH: Final[int] = 63


class PartitionCadence(StrEnum):
    """Time-range granularity for PostgreSQL declarative partitioning."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class PartitionDetachStatus(StrEnum):
    """Outcome status for non-blocking PostgreSQL partition detach operations."""

    DETACHED = "detached"
    NOT_FOUND = "not_found"


__all__ = [
    "MAX_PG_IDENTIFIER_LENGTH",
    "PartitionCadence",
    "PartitionDetachStatus",
]
