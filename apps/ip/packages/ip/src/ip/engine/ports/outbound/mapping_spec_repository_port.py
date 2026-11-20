"""Outbound repository port for MappingSpec persistence in the Control Plane (`ip.mapping_specs`)."""

from __future__ import annotations

from typing import Protocol

from ip.engine.domain.mapping.mapping_spec import MappingSpec


class MappingSpecRepositoryPort(Protocol):
    """Port for persisting and querying declarative Field Mapping Specs."""

    async def save(self, spec: MappingSpec) -> None:
        """Upserts a MappingSpec record."""
        ...

    async def get_by_id(
        self,
        *,
        tenant_id: str,
        mapping_spec_id: str,
    ) -> MappingSpec | None:
        """Retrieves a MappingSpec by ID for a tenant."""
        ...

    async def get_latest_by_target(
        self,
        *,
        tenant_id: str,
        target_connection_id: str,
        target_entity_name: str,
    ) -> MappingSpec | None:
        """Retrieves the latest version of a MappingSpec for a target connection and entity."""
        ...

    async def list_by_tenant(
        self,
        *,
        tenant_id: str,
        source_type: str | None = None,
        target_connection_id: str | None = None,
    ) -> list[MappingSpec]:
        """Lists MappingSpecs for a tenant with optional filtering."""
        ...

    async def delete(
        self,
        *,
        tenant_id: str,
        mapping_spec_id: str,
    ) -> None:
        """Deletes a MappingSpec record for a tenant."""
        ...
