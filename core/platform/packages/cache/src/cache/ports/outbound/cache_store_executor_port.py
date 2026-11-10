"""Abstract capability port for low-level atomic key-value store execution."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from cache.domain.projection import StoreCasExecutionDTO, StoredHashProjectionDTO


class AtomicCacheStoreExecutorPort(Protocol):
    """
    Transport-agnostic Port abstracting atomic hash reads, Lua CAS evaluation,
    key invalidation, and distributed millisecond `NX PX` refresh leases.
    """

    async def read_projection_hash(self, storage_key: str) -> StoredHashProjectionDTO: ...

    async def eval_cas_script(
        self,
        *,
        script: str,
        storage_key: str,
        watermark: int,
        payload_json: str,
        soft_expiry_epoch_ms: int,
        hard_ttl_seconds: int,
    ) -> StoreCasExecutionDTO: ...

    async def delete_storage_keys(self, storage_keys: Sequence[str]) -> int: ...

    async def try_acquire_refresh_lease(
        self,
        lease_key: str,
        lease_ttl_ms: int,
    ) -> bool: ...


__all__ = ["AtomicCacheStoreExecutorPort"]
