"""EDI StoragePort adapter delegating to centralized platform PayloadStoragePort."""

from __future__ import annotations

from seedwork.infra.config_models import PlatformAwsSettings
from storage.config import PlatformStorageSettings
from storage.ports.payload_storage_port import PayloadStoragePort
from storage.provider import StorageProvider

from edi.ports.outbound.storage_port import StoragePort


class PlatformStorageAdapter(StoragePort):
    """Bridges EDI's `StoragePort` to the centralized platform `PayloadStoragePort`."""

    def __init__(self, payload_storage: PayloadStoragePort) -> None:
        self._payload_storage = payload_storage

    @classmethod
    def from_settings(
        cls,
        settings: PlatformStorageSettings,
        *,
        aws_settings: PlatformAwsSettings | None = None,
    ) -> PlatformStorageAdapter:
        """Constructs a `PlatformStorageAdapter` from centralized `PlatformStorageSettings`."""
        return cls(
            payload_storage=StorageProvider.from_settings(
                settings,
                aws_settings=aws_settings,
            )
        )

    async def download(self, uri: str) -> bytes:
        data = await self._payload_storage.download(uri, decompress=False)
        if data is None:
            raise ValueError(f"Storage object not found or invalid URI: {uri}")
        return data

    async def upload(self, payload: bytes, key_prefix: str, file_name: str) -> str:
        key = f"{key_prefix.strip('/')}/{file_name}"
        return await self._payload_storage.upload_key(key=key, payload=payload)
