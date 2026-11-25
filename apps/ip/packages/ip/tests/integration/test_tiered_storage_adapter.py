"""Narrow integration tests for TieredStorageAdapter backed by real FileSystemPayloadStorage."""

from __future__ import annotations

from pathlib import Path

import pytest
from ip.engine.adapters.outbound.storage.tiered_storage_adapter import TieredStorageAdapter
from ip.engine.domain.exceptions import PayloadNotFoundError
from ip.engine.ports.outbound.tiered_storage_port import TieredStorageResultDTO
from storage.adapters.file_system_storage_adapter import FileSystemPayloadStorage

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_tiered_storage_offload_over_threshold_with_filesystem_storage(
    tmp_path: Path,
) -> None:
    storage = FileSystemPayloadStorage(base_directory=tmp_path)
    adapter = TieredStorageAdapter(
        storage_client=storage,
        threshold_bytes=1000,
    )

    large_bytes = b"A" * 2000
    result = await adapter.store(
        tenant_id="ten_999",
        trace_id="trc_large",
        payload_bytes=large_bytes,
    )

    assert result.is_inlined is False
    assert result.raw_payload is None
    assert result.s3_key is not None
    assert result.s3_key.startswith("file://")
    assert f"tenants/ten_999/inbound/trc_large_{result.payload_sha256[:16]}.bin" in result.s3_key
    assert result.payload_size_bytes == 2000

    retrieved_res = await adapter.retrieve(result)
    assert retrieved_res.is_ok is True
    assert retrieved_res.value == large_bytes


@pytest.mark.asyncio
async def test_tiered_storage_retrieve_missing_key_returns_typed_error(
    tmp_path: Path,
) -> None:
    storage = FileSystemPayloadStorage(base_directory=tmp_path)
    adapter = TieredStorageAdapter(storage_client=storage, threshold_bytes=500)
    missing_dto = TieredStorageResultDTO(
        is_inlined=False,
        raw_payload=None,
        s3_key=f"file://{tmp_path.resolve()}/tenants/ten_999/inbound/does_not_exist.bin",
        payload_size_bytes=1024,
        payload_sha256="a" * 64,
    )
    res = await adapter.retrieve(missing_dto)
    assert res.is_err is True
    assert isinstance(res.error, PayloadNotFoundError)
