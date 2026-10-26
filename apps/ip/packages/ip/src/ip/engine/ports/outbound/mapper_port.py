"""MapperPort and MapperRegistryPort for pure L3 normalization mappers."""

from __future__ import annotations

from typing import Protocol

from ip.engine.domain.normalization import (
    MappingContext,
    MappingResult,
    ReplicaSnapshot,
)


class MapperPort(Protocol):
    """The strict boundary contract every L2 -> L3 Canonical Mapper must satisfy."""

    @property
    def mapping_id(self) -> str:
        """Unique business identifier of the mapper (e.g. 'domain.stream_mapper')."""
        ...

    @property
    def mapping_version(self) -> int:
        """Integer version of the mapper contract, bumped on behavioral change."""
        ...

    @property
    def target_types(self) -> tuple[str, ...]:
        """Canonical domain entity types produced by this mapper."""
        ...

    def map(self, replica: ReplicaSnapshot, context: MappingContext) -> MappingResult:
        """Pure mapping function transforming an L2 replica into canonical drafts and rejections."""
        ...


class MapperRegistryPort(Protocol):
    """Registry maintaining active and candidate pure code mappers."""

    def register(self, mapper: MapperPort) -> None:
        """Register a mapper instance by its (mapping_id, mapping_version)."""
        ...

    def get(self, mapping_id: str, mapping_version: int) -> MapperPort | None:
        """Retrieve a registered mapper for a specific version."""
        ...

    def get_latest(self, mapping_id: str) -> MapperPort | None:
        """Retrieve the latest registered version of a mapper."""
        ...

    def list_mappers(self) -> tuple[MapperPort, ...]:
        """List all currently registered mappers."""
        ...
