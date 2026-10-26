"""Tiered S3 JSON payload hydration utility for IP Data Plane repositories."""

from __future__ import annotations

import json

from ip.engine.ports.outbound.tiered_storage_port import (
    TieredStoragePort,
    TieredStorageResultDTO,
)
from seedwork.domain.types import JsonDict


async def hydrate_s3_json_payload(
    storage: TieredStoragePort | None,
    *,
    s3_key: str | None,
    inline_body: JsonDict | None,
    size_bytes: int = 0,
    sha256: str = "",
) -> JsonDict | None:
    """Hydrates an S3-offloaded JSON payload when inline_body is None and storage is configured."""
    if inline_body is not None or not s3_key or storage is None:
        return inline_body
    res = await storage.retrieve(
        TieredStorageResultDTO(
            is_inlined=False,
            raw_payload=None,
            s3_key=s3_key,
            payload_size_bytes=size_bytes,
            payload_sha256=sha256,
        )
    )
    if res.is_err:
        return None
    try:
        decoded = json.loads(res.unwrap().decode("utf-8"))
        if isinstance(decoded, dict):
            return decoded
        return {"_value": decoded}
    except (ValueError, UnicodeDecodeError):
        return None


__all__ = ["hydrate_s3_json_payload"]
