"""EDI StoragePort adapter delegating to centralized platform PayloadStoragePort."""

from __future__ import annotations

from storage.ports.payload_storage_port import PayloadStoragePort
from storage.provider import StorageProvider

from edi.ports.outbound.storage_port import StoragePort


class PlatformStorageAdapter(StoragePort):
    """Bridges EDI's `StoragePort` to the centralized platform `PayloadStoragePort`."""

    def __init__(self, payload_storage: PayloadStoragePort) -> None:
        self._payload_storage = payload_storage

    async def download(self, uri: str) -> bytes:
        data = await self._payload_storage.download(uri, decompress=False)
        if data is None:
            raise ValueError(f"Storage object not found or invalid URI: {uri}")
        return data

    async def upload(self, payload: bytes, key_prefix: str, file_name: str) -> str:
        key = f"{key_prefix.strip('/')}/{file_name}"
        return await self._payload_storage.upload_key(key=key, payload=payload)


class S3StorageClient(PlatformStorageAdapter):
    """Backwards-compatible factory wrapper constructing `PlatformStorageAdapter` via `StorageProvider`."""

    def __init__(
        self,
        bucket_name: str,
        endpoint_url: str | None = None,
        region: str = "us-east-1",
    ) -> None:
        self.bucket_name = bucket_name
        self.endpoint_url = endpoint_url
        self.region = region
        payload_storage = StorageProvider.create_payload_storage(
            bucket=bucket_name,
            endpoint_url=endpoint_url,
            region=region,
        )
        super().__init__(payload_storage=payload_storage)
