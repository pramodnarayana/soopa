"""In-memory MapperRegistry implementation for pure L3 normalization mappers."""

from __future__ import annotations

from ip.engine.domain.normalization import DomainMapperProtocol


class InMemoryMapperRegistry:
    """Thread-safe in-memory registry of pure normalization mappers keyed by (mapping_id, version)."""

    def __init__(self) -> None:
        self._mappers: dict[tuple[str, int], DomainMapperProtocol] = {}

    def register(self, mapper: DomainMapperProtocol) -> None:
        """Register a mapper instance by its (mapping_id, mapping_version)."""
        key = (mapper.mapping_id, mapper.mapping_version)
        self._mappers[key] = mapper

    def get(self, mapping_id: str, mapping_version: int) -> DomainMapperProtocol | None:
        """Retrieve a registered mapper for a specific version."""
        return self._mappers.get((mapping_id, mapping_version))

    def get_latest(self, mapping_id: str) -> DomainMapperProtocol | None:
        """Retrieve the latest registered version of a mapper."""
        matching = [m for (mid, _), m in self._mappers.items() if mid == mapping_id]
        if not matching:
            return None
        return max(matching, key=lambda m: m.mapping_version)

    def list_mappers(self) -> tuple[DomainMapperProtocol, ...]:
        """List all currently registered mappers."""
        return tuple(self._mappers.values())
