"""Outbound repository port for BatchManifest entities."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from typing import Protocol

from ip.engine.domain.intervals.models import (
    BatchManifest,
    BatchReconciliationSummary,
)


class BatchManifestRepositoryPort(Protocol):
    """Outbound repository port for `ip_batch_manifests` OLTP reconciliation ledger."""

    @abstractmethod
    async def save(self, manifest: BatchManifest) -> None:
        """Persists or updates a BatchManifest aggregate and drains its domain/trace events."""
        ...

    @abstractmethod
    async def get_by_id(self, batch_id: str, tenant_id: str) -> BatchManifest | None:
        """Retrieves a BatchManifest by primary key scoped to tenant."""
        ...

    @abstractmethod
    async def get_by_sha256(
        self,
        tenant_id: str,
        connection_id: str,
        payload_sha256: str,
    ) -> BatchManifest | None:
        """Retrieves an existing BatchManifest by SHA-256 fingerprint for idempotent L1 deduplication."""
        ...

    @abstractmethod
    async def list_by_connection(
        self,
        tenant_id: str,
        *,
        connection_id: str | None = None,
        limit: int = 50,
    ) -> Sequence[BatchManifest]:
        """Lists recent interval batch manifests ordered by created_at descending."""
        ...

    @abstractmethod
    async def get_reconciliation_summary(
        self,
        tenant_id: str,
        *,
        connection_id: str | None = None,
    ) -> BatchReconciliationSummary:
        """Computes the Zero-Missing-Data Guarantee summary across all macro-batches."""
        ...


__all__ = ["BatchManifestRepositoryPort"]
