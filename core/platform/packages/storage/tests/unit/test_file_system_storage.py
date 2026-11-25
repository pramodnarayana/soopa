"""Unit tests for FileSystemPayloadStorage and StorageProvider resolution."""

from __future__ import annotations

from pathlib import Path

import pytest
from storage.adapters.file_system_storage_adapter import FileSystemPayloadStorage
from storage.domain.enums import CompressionCodec, StorageBackend
from storage.domain.exceptions import StorageError
from storage.provider import StorageProvider


@pytest.mark.asyncio
async def test_file_system_storage_upload_and_download(tmp_path: Path) -> None:
    storage = FileSystemPayloadStorage(base_directory=tmp_path)

    tenant_id = "ten_test_123"
    message_id = "msg_456"
    test_payload = b"Hello, Sovereign Private Datacenter!"

    uri = await storage.upload(tenant_id=tenant_id, message_id=message_id, payload=test_payload)
    assert uri.startswith("file://")
    assert str(tmp_path) in uri

    retrieved = await storage.download(uri)
    assert retrieved == test_payload


@pytest.mark.asyncio
async def test_file_system_storage_upload_partitioned_with_compression(tmp_path: Path) -> None:
    storage = FileSystemPayloadStorage(base_directory=tmp_path)

    tenant_id = "ten_part_1"
    stream_name = "meter_readings"
    batch_id = "batch_001"
    raw_payload = b'{"meter_id": "M100", "reading": 42.5}' * 10

    uri = await storage.upload_partitioned(
        tenant_id=tenant_id,
        stream_name=stream_name,
        batch_id=batch_id,
        payload=raw_payload,
        extension="json",
        compression=CompressionCodec.GZIP,
    )
    assert uri.startswith("file://")
    assert uri.endswith(".json.gz")

    decompressed = await storage.download(uri, decompress=True)
    assert decompressed == raw_payload

    compressed_raw = await storage.download(uri, decompress=False)
    assert compressed_raw != raw_payload
    assert len(compressed_raw) < len(raw_payload)


@pytest.mark.asyncio
async def test_file_system_storage_stream_upload_and_download(tmp_path: Path) -> None:
    storage = FileSystemPayloadStorage(base_directory=tmp_path)

    tenant_id = "ten_stream_1"
    stream_name = "telemetry"
    batch_id = "batch_stream_001"

    async def sample_stream():
        for i in range(5):
            yield f"line_{i}\n".encode()

    uri = await storage.upload_stream(
        tenant_id=tenant_id,
        stream_name=stream_name,
        batch_id=batch_id,
        stream=sample_stream(),
        extension="csv",
        compression=CompressionCodec.NONE,
    )
    assert uri.startswith("file://")

    # Download via stream
    chunks = []
    async for chunk in storage.download_stream(uri):
        chunks.append(chunk)

    full_payload = b"".join(chunks)
    assert full_payload == b"line_0\nline_1\nline_2\nline_3\nline_4\n"


@pytest.mark.asyncio
async def test_storage_provider_resolves_file_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STORAGE_BACKEND", StorageBackend.FILE.value)
    monkeypatch.setenv("STORAGE_FILE_PATH", str(tmp_path))

    storage = StorageProvider.create_payload_storage()
    assert isinstance(storage, FileSystemPayloadStorage)
    assert storage.base_directory == tmp_path.resolve()


@pytest.mark.asyncio
async def test_file_system_storage_blocks_cwe22_path_traversal(tmp_path: Path) -> None:
    storage = FileSystemPayloadStorage(base_directory=tmp_path)

    with pytest.raises(StorageError, match="escapes base directory"):
        await storage.download("file:///etc/passwd")

    with pytest.raises(StorageError, match="escapes base directory"):
        await storage.download("../../etc/shadow")

    with pytest.raises(StorageError, match="null byte"):
        await storage.download("tenants/a\x00b")


@pytest.mark.asyncio
async def test_file_system_storage_upload_key_and_stream_cleanup_on_failure(tmp_path: Path) -> None:
    storage = FileSystemPayloadStorage(base_directory=tmp_path)

    uri = await storage.upload_key("edi/inbound/po_850.x12", b"ISA*00*...")
    assert await storage.download(uri) == b"ISA*00*..."

    async def failing_stream():
        yield b"partial_chunk"
        raise RuntimeError("Upstream stream aborted")

    with pytest.raises(RuntimeError, match="Upstream stream aborted"):
        await storage.upload_stream(
            tenant_id="ten_1",
            stream_name="stream_fail",
            batch_id="batch_err",
            stream=failing_stream(),
        )

    # Ensure no orphaned .tmp files were left behind
    tmp_files = list(tmp_path.rglob("*.tmp"))
    assert tmp_files == []


@pytest.mark.asyncio
async def test_file_system_storage_boots_and_reads_on_readonly_mount(tmp_path: Path) -> None:
    mount_dir = tmp_path / "nfs-readonly"
    payload_file = mount_dir / "edi" / "inbound" / "doc.x12"
    payload_file.parent.mkdir(parents=True)
    payload_file.write_bytes(b"ISA*00*READONLY")

    mount_dir.chmod(0o555)
    try:
        storage = FileSystemPayloadStorage(base_directory=mount_dir)
        assert await storage.download("edi/inbound/doc.x12") == b"ISA*00*READONLY"
    finally:
        mount_dir.chmod(0o755)
