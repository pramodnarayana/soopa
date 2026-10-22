"""Port contract for storing and querying GlobalEntityMap (GEM) crosswalk entities."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from typing import Protocol

from ip.engine.domain.enums import NormalizedEntityType
from ip.engine.domain.models.global_entity_map import GlobalEntityMap


class GlobalEntityMapRepositoryPort(Protocol):
    """Outbound repository port for cross-system GlobalEntityMap identity resolution."""

    @abstractmethod
    async def save(self, entity_map: GlobalEntityMap) -> None:
        """Persists or updates a GlobalEntityMap crosswalk entry."""
        ...

    @abstractmethod
    async def get_by_source(
        self,
        tenant_id: str,
        entity_domain: NormalizedEntityType,
        source_connection_id: str,
        source_entity_id: str,
    ) -> GlobalEntityMap | None:
        """Resolves a GlobalEntityMap entry by its source system composite key."""
        ...

    @abstractmethod
    async def get_by_canonical_id(
        self,
        tenant_id: str,
        canonical_id: str,
    ) -> Sequence[GlobalEntityMap]:
        """Resolves all GlobalEntityMap entries associated with the given canonical ID."""
        ...
