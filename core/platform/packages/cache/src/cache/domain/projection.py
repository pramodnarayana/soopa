"""Pure Immutable Domain Value Objects and Results for Read Projection Caching."""

from __future__ import annotations

from dataclasses import dataclass

from cache.domain.constants import (
    CacheLookupStatus,
    CacheStoreOperationStatus,
    CacheUpsertStatus,
)


@dataclass(frozen=True)
class StampedProjectionDTO:
    """Serialized read projection paired with its monotonic causal replication watermark."""

    payload_json: str
    source_watermark: int


@dataclass(frozen=True)
class StoredHashProjectionDTO:
    """Raw fields retrieved from the atomic backing store for a projection entry."""

    status: CacheStoreOperationStatus
    payload_json: str | None
    source_watermark: int | None
    soft_expiry_epoch_ms: int | None


@dataclass(frozen=True)
class StoreCasExecutionDTO:
    """Result of executing an atomic Compare-And-Set script on the backing store."""

    status: CacheStoreOperationStatus
    applied: bool


@dataclass(frozen=True)
class CacheLookupResult:
    """First-class cache read outcome eliminating exception-based miss handling."""

    status: CacheLookupStatus
    projection: StampedProjectionDTO | None


@dataclass(frozen=True)
class CacheUpsertResult:
    """First-class monotonic CAS write outcome."""

    status: CacheUpsertStatus
    applied_watermark: int | None


__all__ = [
    "CacheLookupResult",
    "CacheUpsertResult",
    "StampedProjectionDTO",
    "StoreCasExecutionDTO",
    "StoredHashProjectionDTO",
]
