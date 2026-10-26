"""CanonicalEntityRegistry for schema and quality rule definitions."""

from __future__ import annotations

from ip.engine.domain.normalization import CanonicalEntityDefinition


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
