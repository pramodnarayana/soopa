"""Registries for canonical entity specifications, canonical writers, and normalization transformers."""

from __future__ import annotations

from typing import Generic, Protocol, TypeVar

from ip.engine.domain.normalization.transformation import (
    CanonicalEntityDefinition,
    DomainTransformerProtocol,
)


class CanonicalEntityRegistry:
    """Registry maintaining domain canonical entity specifications and quality rules."""

    def __init__(self) -> None:
        self._definitions: dict[str, CanonicalEntityDefinition] = {}

    def register(self, definition: CanonicalEntityDefinition) -> None:
        """Register a canonical entity definition by canonical_type."""
        self._definitions[definition.canonical_type] = definition

    def get(self, canonical_type: str) -> CanonicalEntityDefinition | None:
        """Retrieve the canonical entity definition for a canonical_type."""
        return self._definitions.get(canonical_type)


class CanonicalTypeIdentifiable(Protocol):
    """Protocol for any writer or handler identified by a canonical_type."""

    @property
    def canonical_type(self) -> str:
        """Canonical domain entity type identifier."""
        ...


_WriterT = TypeVar("_WriterT", bound=CanonicalTypeIdentifiable)


class CanonicalWriterRegistry(Generic[_WriterT]):
    """Registry of domain canonical writers keyed by canonical_type."""

    def __init__(self) -> None:
        self._writers: dict[str, _WriterT] = {}

    def register(self, writer: _WriterT) -> None:
        """Register a writer for a canonical_type."""
        self._writers[writer.canonical_type] = writer

    def get(self, canonical_type: str) -> _WriterT | None:
        """Retrieve a registered writer for a canonical_type."""
        return self._writers.get(canonical_type)


class TransformerRegistry:
    """Thread-safe registry of pure normalization transformers keyed by (transformation_id, version)."""

    def __init__(self) -> None:
        self._transformers: dict[tuple[str, int], DomainTransformerProtocol] = {}

    def register(self, transformer: DomainTransformerProtocol) -> None:
        """Register a transformer instance by its (transformation_id, transformation_version)."""
        key = (transformer.transformation_id, transformer.transformation_version)
        self._transformers[key] = transformer

    def get(
        self, transformation_id: str, transformation_version: int
    ) -> DomainTransformerProtocol | None:
        """Retrieve a registered transformer for a specific version."""
        return self._transformers.get((transformation_id, transformation_version))

    def get_latest(self, transformation_id: str) -> DomainTransformerProtocol | None:
        """Retrieve the latest registered version of a transformer."""
        matching = [t for (tid, _), t in self._transformers.items() if tid == transformation_id]
        if not matching:
            return None
        return max(matching, key=lambda t: t.transformation_version)

    def list_transformers(self) -> tuple[DomainTransformerProtocol, ...]:
        """List all currently registered transformers."""
        return tuple(self._transformers.values())


__all__ = [
    "CanonicalEntityRegistry",
    "CanonicalTypeIdentifiable",
    "CanonicalWriterRegistry",
    "TransformerRegistry",
]
