"""Unit tests for TieredStorageAdapter."""

from __future__ import annotations

import json

import pytest
from ip.adapters.outbound.storage.tiered_storage_adapter import TieredStorageAdapter
from storage.ports.payload_storage_port import PayloadStoragePort


class FakePayloadStorage(PayloadStoragePort):
    def __init__(self) -> None:
        self.uploaded: dict[str, bytes] = {}

    async def upload(self, tenant_id: str, message_id: str, payload: bytes) -> str:
        key = f"s3://custom-bucket/{tenant_id}/{message_id}.json"
        self.uploaded[key] = payload
        return key

    async def download(self, s3_key: str) -> bytes | None:
        return self.uploaded.get(s3_key)

    async def generate_presigned_url(
        self,
        storage_uri: str,
        expiry_seconds: int = 3600,
        response_headers: dict[str, str] | None = None,
    ) -> str:
        return f"https://s3.localstack/{storage_uri}"


@pytest.mark.asyncio
async def test_tiered_storage_inline_under_threshold() -> None:
    adapter = TieredStorageAdapter()
    data = {"hello": "world", "status": "active"}
    payload_bytes = json.dumps(data).encode("utf-8")

    result = await adapter.store(
        tenant_id="ten_123",
        trace_id="trc_abc",
        payload_bytes=payload_bytes,
        parsed_payload=data,
    )

    assert result.is_inlined is True
    assert result.s3_key is None
    assert result.raw_payload == data
    assert result.payload_size_bytes == len(payload_bytes)
    assert len(result.payload_sha256) == 64

    # Verify retrieval
    retrieved = await adapter.retrieve(result)
    assert json.loads(retrieved.decode("utf-8")) == data


@pytest.mark.asyncio
async def test_tiered_storage_offload_over_threshold_with_storage_client() -> None:
    fake_storage = FakePayloadStorage()

    adapter = TieredStorageAdapter(
        storage_client=fake_storage,
        threshold_bytes=1000,  # 1 KB threshold for testing
    )

    large_bytes = b"A" * 2000  # 2 KB payload
    result = await adapter.store(
        tenant_id="ten_999",
        trace_id="trc_large",
        payload_bytes=large_bytes,
    )

    assert result.is_inlined is False
    assert result.raw_payload is None
    assert result.s3_key == "s3://custom-bucket/ten_999/trc_large.json"
    assert result.payload_size_bytes == 2000
    assert fake_storage.uploaded["s3://custom-bucket/ten_999/trc_large.json"] == large_bytes

    # Verify retrieval calls download
    retrieved = await adapter.retrieve(result)
    assert retrieved == large_bytes


@pytest.mark.asyncio
async def test_tiered_storage_offload_in_memory_fallback() -> None:
    # When no external S3 client is injected (local fallback mode)
    adapter = TieredStorageAdapter(threshold_bytes=500)
    payload_bytes = b"B" * 600

    result = await adapter.store(
        tenant_id="ten_local",
        trace_id="trc_local_1",
        payload_bytes=payload_bytes,
    )

    assert result.is_inlined is False
    assert result.s3_key == "s3://ip-payloads/ten_local/trc_local_1.json"
    assert result.raw_payload is None

    retrieved = await adapter.retrieve(result)
    assert retrieved == payload_bytes
