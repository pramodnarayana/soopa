"""In-memory TransformerRegistry implementation for pure L3 normalization transformers."""

from __future__ import annotations

from ip.engine.domain.normalization import DomainTransformerProtocol


class InMemoryTransformerRegistry:
    """Thread-safe in-memory registry of pure normalization transformers keyed by (transformation_id, version)."""

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
