"""In-memory CanonicalWriterRegistry implementation."""

from __future__ import annotations

from typing import Generic, Protocol, TypeVar


class CanonicalTypeIdentifiable(Protocol):
    """Protocol for any writer or handler identified by a canonical_type."""

    @property
    def canonical_type(self) -> str:
        """Canonical domain entity type identifier."""
        ...


_WriterT = TypeVar("_WriterT", bound=CanonicalTypeIdentifiable)


class InMemoryCanonicalWriterRegistry(Generic[_WriterT]):
    """In-memory registry of domain canonical writers keyed by canonical_type."""

    def __init__(self) -> None:
        self._writers: dict[str, _WriterT] = {}

    def register(self, writer: _WriterT) -> None:
        """Register a writer for a canonical_type."""
        self._writers[writer.canonical_type] = writer

    def get(self, canonical_type: str) -> _WriterT | None:
        """Retrieve a registered writer for a canonical_type."""
        return self._writers.get(canonical_type)
