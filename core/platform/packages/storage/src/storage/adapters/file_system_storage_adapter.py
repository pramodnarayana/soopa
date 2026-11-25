"""Local and network filesystem (POSIX / NFS / CephFS) payload storage adapter."""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterable
from datetime import UTC, datetime
from pathlib import Path

import structlog

from storage.codecs import StorageCodec
from storage.domain.enums import CompressionCodec
from storage.domain.exceptions import StorageError
from storage.ports.payload_storage_port import PayloadStoragePort

logger = structlog.get_logger(__name__)

_FILE_URI_PREFIX = "file://"
_STREAM_CHUNK_BYTES = 1024 * 1024


class FileSystemPayloadStorage(PayloadStoragePort):
    """High-throughput POSIX / NFS filesystem storage adapter for sovereign on-premise environments."""

    def __init__(self, base_directory: str | Path = "/mnt/storage") -> None:
        self.base_directory = Path(base_directory).resolve()
        if not self.base_directory.exists():
            self.base_directory.mkdir(parents=True, exist_ok=True)

    def build_partitioned_key(
        self,
        tenant_id: str,
        stream_name: str,
        batch_id: str,
        extension: str = "raw",
        compression: CompressionCodec = CompressionCodec.NONE,
    ) -> str:
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        ext = extension.lstrip(".")
        if compression != CompressionCodec.NONE and not ext.endswith(
            compression.file_extension.lstrip(".")
        ):
            ext = f"{ext}{compression.file_extension}"
        return f"tenants/{tenant_id}/{stream_name}/{date_str}/{batch_id}.{ext}"

    def _resolve_path(self, relative_or_uri: str) -> Path:
        """Resolves a storage URI (file://...) or relative path with strict CWE-22 containment."""
        if "\x00" in relative_or_uri:
            logger.error(
                "filesystem_storage_null_byte_path_blocked",
                base_directory=str(self.base_directory),
            )
            raise StorageError("Invalid storage URI containing null byte")

        if relative_or_uri.startswith(_FILE_URI_PREFIX):
            raw_path = relative_or_uri.removeprefix(_FILE_URI_PREFIX)
            candidate = Path(raw_path).resolve()
        else:
            candidate = (self.base_directory / relative_or_uri.lstrip("/")).resolve()

        if not candidate.is_relative_to(self.base_directory):
            logger.error(
                "filesystem_storage_path_traversal_blocked",
                storage_uri=relative_or_uri,
                resolved_path=str(candidate),
                base_directory=str(self.base_directory),
            )
            raise StorageError(f"Storage URI escapes base directory: {relative_or_uri}")
        return candidate

    async def upload(self, tenant_id: str, message_id: str, payload: bytes) -> str:
        key = f"tenants/{tenant_id}/inbound/{message_id}.bin"
        return await self.upload_key(key=key, payload=payload)

    async def upload_key(self, key: str, payload: bytes) -> str:
        target_path = self._resolve_path(key.lstrip("/"))
        await asyncio.to_thread(self._atomic_write, target_path, payload)
        return f"{_FILE_URI_PREFIX}{target_path}"

    async def upload_partitioned(
        self,
        tenant_id: str,
        stream_name: str,
        batch_id: str,
        payload: bytes,
        extension: str = "raw",
        compression: CompressionCodec = CompressionCodec.NONE,
    ) -> str:
        key = self.build_partitioned_key(
            tenant_id=tenant_id,
            stream_name=stream_name,
            batch_id=batch_id,
            extension=extension,
            compression=compression,
        )
        data = StorageCodec.compress(payload, compression)
        target_path = self._resolve_path(key)
        await asyncio.to_thread(self._atomic_write, target_path, data)
        return f"{_FILE_URI_PREFIX}{target_path}"

    async def upload_stream(
        self,
        tenant_id: str,
        stream_name: str,
        batch_id: str,
        stream: AsyncIterable[bytes],
        extension: str = "raw",
        compression: CompressionCodec = CompressionCodec.NONE,
        content_type: str = "application/octet-stream",
    ) -> str:
        key = self.build_partitioned_key(
            tenant_id=tenant_id,
            stream_name=stream_name,
            batch_id=batch_id,
            extension=extension,
            compression=compression,
        )
        target_path = self._resolve_path(key)
        await asyncio.to_thread(target_path.parent.mkdir, parents=True, exist_ok=True)
        temp_path = target_path.with_name(
            f".{target_path.name}.{os.getpid()}.{os.urandom(6).hex()}.tmp"
        )

        compressed_stream = StorageCodec.compress_stream(stream, compression)
        completed = False
        file_handle = await asyncio.to_thread(temp_path.open, "wb")
        try:
            async for chunk in compressed_stream:
                await asyncio.to_thread(file_handle.write, chunk)
            await asyncio.to_thread(file_handle.close)
            await asyncio.to_thread(os.replace, temp_path, target_path)
            completed = True
        finally:
            if not file_handle.closed:
                with contextlib.suppress(OSError):
                    await asyncio.to_thread(file_handle.close)
            if not completed:
                with contextlib.suppress(OSError):
                    await asyncio.to_thread(temp_path.unlink, missing_ok=True)

        return f"{_FILE_URI_PREFIX}{target_path}"

    async def download(self, storage_uri: str, decompress: bool = True) -> bytes | None:
        target_path = self._resolve_path(storage_uri)
        exists = await asyncio.to_thread(target_path.is_file)
        if not exists:
            return None

        raw_bytes = await asyncio.to_thread(target_path.read_bytes)
        if not decompress:
            return raw_bytes

        key = str(target_path)
        if key.endswith(CompressionCodec.GZIP.file_extension):
            return StorageCodec.decompress(raw_bytes, CompressionCodec.GZIP)
        if key.endswith(CompressionCodec.ZSTD.file_extension):
            return StorageCodec.decompress(raw_bytes, CompressionCodec.ZSTD)

        return raw_bytes

    async def download_stream(self, storage_uri: str) -> AsyncIterable[bytes]:
        target_path = self._resolve_path(storage_uri)
        exists = await asyncio.to_thread(target_path.is_file)
        if not exists:
            return

        file_handle = await asyncio.to_thread(target_path.open, "rb")
        try:
            while True:
                chunk = await asyncio.to_thread(file_handle.read, _STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                yield chunk
        finally:
            with contextlib.suppress(OSError):
                await asyncio.to_thread(file_handle.close)

    async def generate_presigned_url(
        self,
        storage_uri: str,
        expiry_seconds: int = 3600,
        response_headers: dict[str, str] | None = None,
    ) -> str:
        """For local filesystem storage, returns the validated canonical file URI."""
        target_path = self._resolve_path(storage_uri)
        return f"{_FILE_URI_PREFIX}{target_path}"

    @staticmethod
    def _atomic_write(target_path: Path, data: bytes) -> None:
        """Writes data atomically using temporary file rename with failure cleanup."""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.with_name(
            f".{target_path.name}.{os.getpid()}.{os.urandom(6).hex()}.tmp"
        )
        written = False
        try:
            temp_path.write_bytes(data)
            os.replace(temp_path, target_path)
            written = True
        finally:
            if not written:
                with contextlib.suppress(OSError):
                    temp_path.unlink(missing_ok=True)
