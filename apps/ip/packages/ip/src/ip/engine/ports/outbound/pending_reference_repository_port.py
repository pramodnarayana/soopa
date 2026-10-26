"""PendingReferenceRepositoryPort for tracking and resolving late-arriving canonical references."""

from __future__ import annotations

from typing import Protocol

from ip.engine.domain.normalization import PendingReferenceEntry


class PendingReferenceRepositoryPort(Protocol):
    """Port for tracking and resolving references to canonical records that arrive out of order."""

    async def record_pending(self, entry: PendingReferenceEntry) -> None:
        """Record an unresolved reference waiting for its target canonical record."""
        ...

    async def resolve_pending_for_target(
        self,
        *,
        tenant_id: str,
        source_connection_id: str,
        target_canonical_type: str,
        target_source_id: str,
    ) -> list[PendingReferenceEntry]:
        """Mark as resolved and return all pending references matching a newly arrived target."""
        ...
