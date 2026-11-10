"""
Deterministic In-Memory Fakes for `cache.testing`.

Implements the exact monotonic watermark CAS, soft/hard TTL expiration, and
millisecond `NX PX` lease semantics as Valkey/Redis without external mocks.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from cache.domain.constants import CacheStoreOperationStatus
from cache.domain.models import StoreCasExecutionDTO, StoredHashProjectionDTO
from cache.ports.outbound.cache_store_executor_port import AtomicCacheStoreExecutorPort


@dataclass(frozen=True)
class _InMemoryEntry:
    watermark: int
    payload_json: str
    soft_expiry_epoch_ms: int
    hard_expiry_epoch_ms: int


class InMemoryAtomicCacheStoreExecutor(AtomicCacheStoreExecutorPort):
    """Coroutine-safe deterministic fake for `AtomicCacheStoreExecutorPort`."""

    def __init__(
        self,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self._clock_ms: Callable[[], int] = (
            clock_ms if clock_ms is not None else lambda: int(time.time() * 1000)
        )
        self._entries: dict[str, _InMemoryEntry] = {}
        self._leases: dict[str, int] = {}
        self.simulate_unavailable: bool = False

    def _evict_if_expired(self, storage_key: str, now_ms: int) -> _InMemoryEntry | None:
        entry = self._entries.get(storage_key)
        if entry is None:
            return None
        if now_ms >= entry.hard_expiry_epoch_ms:
            del self._entries[storage_key]
            return None
        return entry

    async def read_projection_hash(self, storage_key: str) -> StoredHashProjectionDTO:
        if self.simulate_unavailable:
            return StoredHashProjectionDTO(
                status=CacheStoreOperationStatus.UNAVAILABLE,
                payload_json=None,
                source_watermark=None,
                soft_expiry_epoch_ms=None,
            )
        now_ms = self._clock_ms()
        entry = self._evict_if_expired(storage_key, now_ms)
        if entry is None:
            return StoredHashProjectionDTO(
                status=CacheStoreOperationStatus.OK,
                payload_json=None,
                source_watermark=None,
                soft_expiry_epoch_ms=None,
            )
        return StoredHashProjectionDTO(
            status=CacheStoreOperationStatus.OK,
            payload_json=entry.payload_json,
            source_watermark=entry.watermark,
            soft_expiry_epoch_ms=entry.soft_expiry_epoch_ms,
        )

    async def eval_cas_script(
        self,
        *,
        script: str,
        storage_key: str,
        watermark: int,
        payload_json: str,
        soft_expiry_epoch_ms: int,
        hard_ttl_seconds: int,
    ) -> StoreCasExecutionDTO:
        _ = script
        if self.simulate_unavailable:
            return StoreCasExecutionDTO(
                status=CacheStoreOperationStatus.UNAVAILABLE,
                applied=False,
            )
        now_ms = self._clock_ms()
        existing = self._evict_if_expired(storage_key, now_ms)
        if existing is None or watermark >= existing.watermark:
            self._entries[storage_key] = _InMemoryEntry(
                watermark=watermark,
                payload_json=payload_json,
                soft_expiry_epoch_ms=soft_expiry_epoch_ms,
                hard_expiry_epoch_ms=now_ms + (hard_ttl_seconds * 1000),
            )
            return StoreCasExecutionDTO(
                status=CacheStoreOperationStatus.OK,
                applied=True,
            )
        return StoreCasExecutionDTO(
            status=CacheStoreOperationStatus.OK,
            applied=False,
        )

    async def delete_storage_keys(self, storage_keys: Sequence[str]) -> int:
        if self.simulate_unavailable:
            return 0
        deleted = 0
        for key in storage_keys:
            if key in self._entries:
                del self._entries[key]
                deleted += 1
        return deleted

    async def try_acquire_refresh_lease(
        self,
        lease_key: str,
        lease_ttl_ms: int,
    ) -> bool:
        if self.simulate_unavailable:
            return False
        now_ms = self._clock_ms()
        exp = self._leases.get(lease_key)
        if exp is not None and now_ms < exp:
            return False
        self._leases[lease_key] = now_ms + lease_ttl_ms
        return True


__all__ = ["InMemoryAtomicCacheStoreExecutor"]
