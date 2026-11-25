"""Port for universal payload object storage (core/platform/packages/storage)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterable

from storage.domain.enums import CompressionCodec


class PayloadStoragePort(ABC):
    """Port for storing payloads and high-volume streams externally (S3 / MinIO)."""

    @abstractmethod
    async def upload(self, tenant_id: str, message_id: str, payload: bytes) -> str:
        """Uploads a payload under standard inbound key and returns universal storage URI."""
        ...

    async def upload_key(self, key: str, payload: bytes) -> str:
        """Uploads a payload at an exact key path and returns universal storage URI."""
        parts = key.strip("/").split("/", 1)
        prefix = parts[0] if len(parts) > 1 else "default"
        leaf = parts[1] if len(parts) > 1 else parts[0]
        return await self.upload(tenant_id=prefix, message_id=leaf, payload=payload)

    @abstractmethod
    async def upload_partitioned(
        self,
        tenant_id: str,
        stream_name: str,
        batch_id: str,
        payload: bytes,
        extension: str = "raw",
        compression: CompressionCodec = CompressionCodec.NONE,
    ) -> str:
        """Uploads a payload to a partitioned path: tenants/{tenant_id}/{stream_name}/{YYYY-MM-DD}/{batch_id}.{ext}."""
        ...

    @abstractmethod
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
        """Zero-RAM streaming multipart upload for high-volume streams."""
        ...

    @abstractmethod
    async def download(self, storage_uri: str, decompress: bool = True) -> bytes | None:
        """Downloads a payload from the given storage URI."""
        ...

    @abstractmethod
    def download_stream(self, storage_uri: str) -> AsyncIterable[bytes]:
        """Streams bytes of an object without loading the entire payload into RAM."""
        ...

    @abstractmethod
    async def generate_presigned_url(
        self,
        storage_uri: str,
        expiry_seconds: int = 3600,
        response_headers: dict[str, str] | None = None,
    ) -> str:
        """Generates a presigned URL for direct browser or client download."""
        ...

    @abstractmethod
    def build_partitioned_key(
        self,
        tenant_id: str,
        stream_name: str,
        batch_id: str,
        extension: str = "raw",
        compression: CompressionCodec = CompressionCodec.NONE,
    ) -> str:
        """Builds the canonical S3 key partitioned by date and stream."""
        ...
