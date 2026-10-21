"""Tiered storage adapter implementing the <64KB inline vs >=64KB S3 offload strategy."""

from __future__ import annotations

import base64
import hashlib
import json

import structlog
from ip.domain.constants import DEFAULT_INLINE_THRESHOLD_BYTES
from ip.domain.types import JsonDict
from ip.ports.outbound.tiered_storage_port import (
    TieredStoragePort,
    TieredStorageResultDTO,
)
from storage.ports.payload_storage_port import PayloadStoragePort

logger = structlog.get_logger(__name__)


class TieredStorageAdapter(TieredStoragePort):
    """Adapts payload storage by storing small payloads inline and offloading large payloads to S3."""

    def __init__(
        self,
        storage_client: PayloadStoragePort | None = None,
        threshold_bytes: int = DEFAULT_INLINE_THRESHOLD_BYTES,
    ) -> None:
        self._storage_client = storage_client
        self._threshold_bytes = threshold_bytes
        self._in_memory_blobs: dict[str, bytes] = {}

    async def store(
        self,
        tenant_id: str,
        trace_id: str,
        payload_bytes: bytes,
        parsed_payload: JsonDict | None = None,
    ) -> TieredStorageResultDTO:
        size_bytes = len(payload_bytes)
        sha256_hash = hashlib.sha256(payload_bytes).hexdigest()

        if size_bytes < self._threshold_bytes:
            # Inline storage (<64 KB)
            if parsed_payload is not None:
                json_data = parsed_payload
            else:
                try:
                    decoded_text = payload_bytes.decode("utf-8")
                    parsed_val = json.loads(decoded_text)
                    if isinstance(parsed_val, dict):
                        json_data = parsed_val
                    else:
                        json_data = {"__wrapped_scalar__": parsed_val}
                except (json.JSONDecodeError, UnicodeDecodeError):
                    json_data = {"raw_b64": base64.b64encode(payload_bytes).decode("ascii")}

            return TieredStorageResultDTO(
                is_inlined=True,
                raw_payload=json_data,
                s3_key=None,
                payload_size_bytes=size_bytes,
                payload_sha256=sha256_hash,
            )

        # Offloaded storage (>=64 KB)
        s3_key: str
        if self._storage_client is not None:
            s3_key = await self._storage_client.upload(
                tenant_id=tenant_id,
                message_id=trace_id,
                payload=payload_bytes,
            )
        else:
            s3_key = f"s3://ip-payloads/{tenant_id}/{trace_id}.json"
            self._in_memory_blobs[s3_key] = payload_bytes

        logger.info(
            "tiered_storage_offloaded_to_s3",
            tenant_id=tenant_id,
            trace_id=trace_id,
            size_bytes=size_bytes,
            s3_key=s3_key,
        )

        return TieredStorageResultDTO(
            is_inlined=False,
            raw_payload=None,
            s3_key=s3_key,
            payload_size_bytes=size_bytes,
            payload_sha256=sha256_hash,
        )

    async def retrieve(self, result: TieredStorageResultDTO) -> bytes:
        if result.is_inlined and result.raw_payload is not None:
            if "raw_b64" in result.raw_payload and len(result.raw_payload) == 1:
                return base64.b64decode(str(result.raw_payload["raw_b64"]))
            if "__wrapped_scalar__" in result.raw_payload and len(result.raw_payload) == 1:
                return json.dumps(
                    result.raw_payload["__wrapped_scalar__"], separators=(",", ":")
                ).encode("utf-8")
            return json.dumps(result.raw_payload, separators=(",", ":")).encode("utf-8")

        if result.s3_key is not None:
            if self._storage_client is not None:
                data = await self._storage_client.download(result.s3_key)
                if data is not None:
                    return data
            elif result.s3_key in self._in_memory_blobs:
                return self._in_memory_blobs[result.s3_key]

        raise ValueError(f"Unable to retrieve payload for record with s3_key={result.s3_key}")
