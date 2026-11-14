"""Port contract for reading typed canonical domain entities (L3 Normalized Layer)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from ip.engine.domain.normalization.normalized_record import NormalizedRecord


class CanonicalReaderPort(Protocol):
    """Protocol implemented by domain database adapters to read typed canonical entities."""

    @property
    def canonical_type(self) -> str:
        """Canonical domain entity type handled by this reader (e.g. 'domain.entity_type')."""
        ...

    async def get_by_id(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        record_id: str,
    ) -> NormalizedRecord | None:
        """Fetch a single normalized record by canonical ID."""
        ...

    async def get_by_trace_id(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        trace_id: str,
    ) -> Sequence[NormalizedRecord]:
        """Fetch normalized records associated with a trace_id."""
        ...

    async def list_records(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        connection_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[NormalizedRecord]:
        """List normalized records for UI inspection and querying."""
        ...


class CanonicalReaderRegistryPort(Protocol):
    """Registry maintaining domain canonical readers by canonical_type."""

    def register(self, reader: CanonicalReaderPort) -> None:
        """Register a reader for a canonical_type."""
        ...

    def get(self, canonical_type: str) -> CanonicalReaderPort | None:
        """Retrieve a registered reader for a canonical_type."""
        ...

    def all_readers(self) -> Sequence[CanonicalReaderPort]:
        """Retrieve all registered readers."""
        ...
