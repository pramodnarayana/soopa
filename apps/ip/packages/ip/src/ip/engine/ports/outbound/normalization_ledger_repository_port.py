"""NormalizationLedgerRepositoryPort for L3 normalization lineage and version guard."""

from __future__ import annotations

from typing import Protocol

from ip.engine.domain.normalization import NormalizationLedgerEntry


class NormalizationLedgerRepositoryPort(Protocol):
    """Port for recording and querying normalization audit ledger entries on tenant shards."""

    async def get_latest_version(
        self,
        *,
        tenant_id: str,
        replica_record_id: str,
        transformation_id: str,
        transformation_version: int,
    ) -> int | None:
        """Retrieve the highest processed replica version for this replica and transformer version."""
        ...

    async def get_produced_refs(
        self,
        *,
        tenant_id: str,
        replica_record_id: str,
        transformation_id: str,
        transformation_version: int,
    ) -> tuple[tuple[str, str], ...]:
        """Retrieve the canonical references produced by the most recent normalization run."""
        ...

    async def get_latest_produced_refs(
        self,
        *,
        tenant_id: str,
        replica_record_id: str,
        transformation_id: str,
    ) -> tuple[tuple[str, str], ...]:
        """Retrieve canonical references produced by the most recent normalization run across all transformation versions."""
        ...

    async def record_entry(self, entry: NormalizationLedgerEntry) -> None:
        """Insert or update a normalization ledger entry."""
        ...
