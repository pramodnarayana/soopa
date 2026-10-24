"""Pure unit tests for TieredStorageAdapter inline (<64KB) payload handling."""

from __future__ import annotations

import json

import pytest
from ip.engine.adapters.outbound.storage.tiered_storage_adapter import TieredStorageAdapter
from ip.engine.domain.exceptions import PayloadNotFoundError
from ip.engine.ports.outbound.tiered_storage_port import TieredStorageResultDTO
from seedwork.domain.types import JsonDict


@pytest.mark.asyncio
async def test_tiered_storage_inline_under_threshold() -> None:
    adapter = TieredStorageAdapter()
    data: JsonDict = {"hello": "world", "status": "active"}
    payload_bytes = json.dumps(data).encode("utf-8")

    result = await adapter.store(
        tenant_id="ten_123",
        trace_id="trc_abc",
        payload_bytes=payload_bytes,
        parsed_payload=data,
    )

    assert result.is_inlined is True
    assert result.s3_key is None
    assert isinstance(result.raw_payload, dict)
    assert result.raw_payload["hello"] == "world"
    assert result.raw_payload["status"] == "active"
    assert "__raw_payload_b64__" in result.raw_payload
    assert result.payload_size_bytes == len(payload_bytes)
    assert len(result.payload_sha256) == 64

    retrieved_res = await adapter.retrieve(result)
    assert retrieved_res.is_ok is True
    assert retrieved_res.value == payload_bytes


@pytest.mark.asyncio
async def test_tiered_storage_inline_non_json_bytes_base64_roundtrip() -> None:
    adapter = TieredStorageAdapter(threshold_bytes=10000)
    binary_data = bytes([0x00, 0xFF, 0xFE, 0x80, 0x55, 0xAA, 0x12, 0x34])

    result = await adapter.store(
        tenant_id="ten_binary",
        trace_id="trc_bin_1",
        payload_bytes=binary_data,
        parsed_payload=None,
    )

    assert result.is_inlined is True
    assert result.s3_key is None
    assert isinstance(result.raw_payload, dict)
    assert "__raw_payload_b64__" in result.raw_payload

    retrieved_res = await adapter.retrieve(result)
    assert retrieved_res.is_ok is True
    assert retrieved_res.value == binary_data


@pytest.mark.asyncio
async def test_tiered_storage_retrieve_unmatched_bucket_returns_typed_error() -> None:
    adapter = TieredStorageAdapter(threshold_bytes=500)
    missing_dto = TieredStorageResultDTO(
        is_inlined=False,
        raw_payload=None,
        s3_key="s3://unregistered-bucket/missing.json",
        payload_size_bytes=1024,
        payload_sha256="a" * 64,
    )
    res = await adapter.retrieve(missing_dto)
    assert res.is_err is True
    assert isinstance(res.error, PayloadNotFoundError)
    assert res.error.s3_key == "s3://unregistered-bucket/missing.json"


@pytest.mark.asyncio
async def test_tiered_storage_retrieve_malformed_base64_returns_typed_error() -> None:
    adapter = TieredStorageAdapter()
    corrupt_dto = TieredStorageResultDTO(
        is_inlined=True,
        raw_payload={"__raw_payload_b64__": "not-valid-base-64!!!"},
        s3_key=None,
        payload_size_bytes=100,
        payload_sha256="b" * 64,
    )
    res = await adapter.retrieve(corrupt_dto)
    assert res.is_err is True
    assert isinstance(res.error, PayloadNotFoundError)


@pytest.mark.asyncio
async def test_tiered_storage_inline_json_array() -> None:
    adapter = TieredStorageAdapter()
    data: list[JsonDict] = [
        {"id": "rec_1", "status": "active"},
        {"id": "rec_2", "status": "pending"},
    ]
    payload_bytes = json.dumps(data).encode("utf-8")

    result = await adapter.store(
        tenant_id="ten_array",
        trace_id="trc_arr_1",
        payload_bytes=payload_bytes,
        parsed_payload=data,
    )

    assert result.is_inlined is True
    assert result.s3_key is None
    assert isinstance(result.raw_payload, dict)
    assert "__wrapped_scalar__" in result.raw_payload
    assert result.raw_payload["__wrapped_scalar__"] == data
    assert "__raw_payload_b64__" in result.raw_payload

    retrieved_res = await adapter.retrieve(result)
    assert retrieved_res.is_ok is True
    assert retrieved_res.value == payload_bytes
