from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from seedwork.domain.types import JsonDict

if TYPE_CHECKING:
    from ip.engine.domain.normalization import CanonicalEntityDefinition
    from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkPort


class CanonicalWriterPort(Protocol):
    """Protocol implemented by domain database adapters to persist typed canonical entities."""

    @property
    def canonical_type(self) -> str:
        """Canonical domain entity type handled by this writer (e.g. 'domain.entity_type')."""
        ...

    async def upsert(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
        fields: JsonDict,
        extensions: JsonDict,
        trace_id: str,
        mapping_id: str,
        mapping_version: int,
        replica_id: str,
        replica_version: int,
        correlation_id: str | None = None,
    ) -> None:
        """Upsert a canonical domain entity instance."""
        ...

    async def soft_delete(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
        trace_id: str,
        correlation_id: str | None = None,
    ) -> None:
        """Soft-delete a canonical domain entity instance on source tombstone."""
        ...

    async def resolve_id(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
    ) -> str | None:
        """Resolve the internal canonical ID for a source_id if it exists and is not deleted."""
        ...

    async def resolve_reference(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
        field_name: str,
        target_id: str,
        trace_id: str,
    ) -> None:
        """Back-patch a foreign key reference field when a late-arriving target entity arrives."""
        ...


class CanonicalWriterRegistryPort(Protocol):
    """Registry maintaining domain canonical writers by canonical_type."""

    def register(self, writer: CanonicalWriterPort) -> None:
        """Register a writer for a canonical_type."""
        ...

    def get(self, canonical_type: str) -> CanonicalWriterPort | None:
        """Retrieve a registered writer for a canonical_type."""
        ...


class CanonicalEntityRegistryPort(Protocol):
    """Registry maintaining domain canonical entity specifications and quality rules."""

    def register(self, definition: CanonicalEntityDefinition) -> None:
        """Register a canonical entity definition by canonical_type."""
        ...

    def get(self, canonical_type: str) -> CanonicalEntityDefinition | None:
        """Retrieve the canonical entity definition for a canonical_type."""
        ...
