"""Port contract for tiered payload storage (inlined JSON vs S3 / MinIO blob)."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import Protocol

from ip.domain.types import JsonDict


@dataclass(frozen=True)
class TieredStorageResultDTO:
    """Outcome of storing a payload via tiered storage."""

    is_inlined: bool
    raw_payload: JsonDict | None
    s3_key: str | None
    payload_size_bytes: int
    payload_sha256: str


class TieredStoragePort(Protocol):
    """Port deciding whether to store payloads inline or in object storage."""

    @abstractmethod
    async def store(
        self,
        tenant_id: str,
        trace_id: str,
        payload_bytes: bytes,
        parsed_payload: JsonDict | None = None,
    ) -> TieredStorageResultDTO:
        """Stores the payload inlined or offloaded to object storage based on threshold."""
        ...

    @abstractmethod
    async def retrieve(self, result: TieredStorageResultDTO) -> bytes:
        """Retrieves raw payload bytes regardless of whether inlined or in S3."""
        ...
