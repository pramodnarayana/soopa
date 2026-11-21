"""Universal OLAP exceptions (core/platform/packages/database/olap)."""

from __future__ import annotations


class OlapError(Exception):
    """Base exception for all OLAP database operations."""


class OlapConnectionError(OlapError):
    """Raised when connection to OLAP cluster fails."""


class OlapQueryError(OlapError):
    """Raised when an OLAP query or statement fails."""

    def __init__(self, message: str, query: str | None = None) -> None:
        super().__init__(message)
        self.query = query
