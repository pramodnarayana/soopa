"""Storage domain exceptions."""

from __future__ import annotations


class StorageError(Exception):
    """Base exception for all storage domain failures."""


class ObjectNotFoundError(StorageError):
    """Raised when an object cannot be found in storage."""

    def __init__(self, uri: str) -> None:
        super().__init__(f"Storage object not found at URI: {uri}")
        self.uri = uri


class CompressionError(StorageError):
    """Raised when compression or decompression fails."""
