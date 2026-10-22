"""Tiered storage adapter implementing the <64KB inline vs >=64KB S3 offload strategy."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json

import structlog
from botocore.exceptions import BotoCoreError, ClientError
from ip.engine.domain.constants import DEFAULT_INLINE_THRESHOLD_BYTES
from ip.engine.domain.exceptions import PayloadNotFoundError, Result
from ip.engine.ports.outbound.tiered_storage_port import (
    TieredStoragePort,
    TieredStorageResultDTO,
)
from seedwork.domain.types import JsonDict
from storage.ports.payload_storage_port import PayloadStoragePort
from storage.provider import StorageProvider

logger = structlog.get_logger(__name__)

DEFAULT_IP_PAYLOAD_BUCKET = "ip-payloads"
RESERVED_RAW_BYTES_KEY = "__raw_payload_b64__"


class TieredStorageAdapter(TieredStoragePort):
    """Adapts payload storage by storing small payloads inline (<64KB) and offloading large payloads (>=64KB) to S3."""

    def __init__(
        self,
        storage_client: PayloadStoragePort | None = None,
        threshold_bytes: int = DEFAULT_INLINE_THRESHOLD_BYTES,
    ) -> None:
        self._storage_client: PayloadStoragePort = (
            storage_client
            if storage_client is not None
            else StorageProvider.create_payload_storage(bucket=DEFAULT_IP_PAYLOAD_BUCKET)
        )
        self._threshold_bytes = threshold_bytes

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
            raw_b64 = base64.b64encode(payload_bytes).decode("ascii")
            if parsed_payload is not None:
                json_data = dict(parsed_payload)
            else:
                try:
                    decoded_text = payload_bytes.decode("utf-8")
                    parsed_val = json.loads(decoded_text)
                    if isinstance(parsed_val, dict):
                        json_data = dict(parsed_val)
                    else:
                        json_data = {"__wrapped_scalar__": parsed_val}
                except (json.JSONDecodeError, UnicodeDecodeError):
                    json_data = {}

            # Escape any caller field that collides with reserved storage metadata
            if RESERVED_RAW_BYTES_KEY in json_data:
                json_data[f"_escaped_{RESERVED_RAW_BYTES_KEY}"] = json_data.pop(
                    RESERVED_RAW_BYTES_KEY
                )

            json_data[RESERVED_RAW_BYTES_KEY] = raw_b64

            return TieredStorageResultDTO(
                is_inlined=True,
                raw_payload=json_data,
                s3_key=None,
                payload_size_bytes=size_bytes,
                payload_sha256=sha256_hash,
            )

        # Offloaded storage (>=64 KB) via PayloadStoragePort with unique per-payload identifier
        message_id = f"{trace_id}_{sha256_hash[:16]}"
        s3_key = await self._storage_client.upload(
            tenant_id=tenant_id,
            message_id=message_id,
            payload=payload_bytes,
        )

        logger.info(
            "tiered_storage_offloaded_to_s3",
            tenant_id=tenant_id,
            trace_id=trace_id,
            message_id=message_id,
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

    async def retrieve(self, result: TieredStorageResultDTO) -> Result[bytes, PayloadNotFoundError]:
        if result.is_inlined and result.raw_payload is not None:
            if RESERVED_RAW_BYTES_KEY in result.raw_payload:
                raw_b64_val = result.raw_payload[RESERVED_RAW_BYTES_KEY]
                try:
                    return Result.ok(base64.b64decode(str(raw_b64_val), validate=True))
                except (ValueError, binascii.Error) as exc:
                    logger.error(
                        "tiered_storage_corrupted_base64_payload",
                        error=str(exc),
                    )
                    return Result.fail(
                        PayloadNotFoundError(
                            s3_key=result.s3_key,
                            message=f"Malformed base64 in inline payload: {exc}",
                            details={"error": str(exc)},
                        )
                    )

            if "raw_b64" in result.raw_payload and len(result.raw_payload) == 1:
                try:
                    return Result.ok(
                        base64.b64decode(str(result.raw_payload["raw_b64"]), validate=True)
                    )
                except (ValueError, binascii.Error) as exc:
                    return Result.fail(
                        PayloadNotFoundError(
                            s3_key=result.s3_key,
                            message=f"Malformed base64 in inline payload: {exc}",
                            details={"error": str(exc)},
                        )
                    )

            if "__wrapped_scalar__" in result.raw_payload and len(result.raw_payload) == 1:
                return Result.ok(
                    json.dumps(
                        result.raw_payload["__wrapped_scalar__"], separators=(",", ":")
                    ).encode("utf-8")
                )
            return Result.ok(json.dumps(result.raw_payload, separators=(",", ":")).encode("utf-8"))

        if result.s3_key is not None:
            try:
                data = await self._storage_client.download(result.s3_key)
                if data is not None:
                    return Result.ok(data)
            except (ClientError, BotoCoreError, OSError) as exc:
                logger.error(
                    "tiered_storage_s3_download_failed",
                    s3_key=result.s3_key,
                    error=str(exc),
                )

        return Result.fail(
            PayloadNotFoundError(
                s3_key=result.s3_key,
                message=f"Unable to retrieve payload for record with s3_key={result.s3_key}",
                details={"s3_key": result.s3_key},
            )
        )
