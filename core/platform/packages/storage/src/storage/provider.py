"""Universal Platform Composition Root for payload object and file storage."""

from __future__ import annotations

import os
from pathlib import Path

from seedwork.infra.config_models import PlatformAwsSettings

from storage.adapters.file_system_storage_adapter import FileSystemPayloadStorage
from storage.adapters.s3_storage_adapter import Aioboto3PayloadStorage
from storage.domain.enums import StorageBackend
from storage.ports.payload_storage_port import PayloadStoragePort


class StorageProvider:
    @staticmethod
    def resolve_backend(backend: StorageBackend | str | None = None) -> StorageBackend:
        """Resolves the configured StorageBackend enum from parameter or environment."""
        if isinstance(backend, StorageBackend):
            return backend
        raw = (
            (
                backend
                or os.getenv("STORAGE_BACKEND")
                or (
                    StorageBackend.FILE.value
                    if os.getenv("STORAGE_FILE_PATH") or os.getenv("PAYLOAD_STORAGE_PATH")
                    else StorageBackend.S3.value
                )
            )
            .strip()
            .lower()
        )
        try:
            return StorageBackend(raw)
        except ValueError as exc:
            raise ValueError(
                f"Unsupported STORAGE_BACKEND '{raw}'. "
                f"Supported backends: {[b.value for b in StorageBackend]}"
            ) from exc

    @staticmethod
    def create_payload_storage(
        bucket: str | None = None,
        base_directory: str | Path | None = None,
        backend: StorageBackend | str | None = None,
        endpoint_url: str | None = None,
        region: str | None = None,
    ) -> PayloadStoragePort:
        """Creates a PayloadStoragePort based on environment variables or explicit parameters.

        Supported backends via STORAGE_BACKEND:
        - 'file' / 'filesystem' / 'nfs' / 'posix': Uses FileSystemPayloadStorage on local / shared disk.
        - 's3' / 'minio' (default): Uses Aioboto3PayloadStorage pointing to AWS S3 or on-prem MinIO.
        """
        selected_backend = StorageProvider.resolve_backend(backend)
        if selected_backend.is_filesystem:
            mount_path = (
                base_directory
                or os.getenv("PAYLOAD_STORAGE_PATH")
                or os.getenv("STORAGE_FILE_PATH")
                or "/mnt/storage"
            )
            return FileSystemPayloadStorage(base_directory=mount_path)

        aws_settings = PlatformAwsSettings()
        bucket_name: str = bucket or os.getenv("S3_BUCKET") or "edi-as2-payloads"
        s3_endpoint = endpoint_url or os.getenv("S3_ENDPOINT_URL") or aws_settings.endpoint_url
        access_key = os.getenv("S3_ACCESS_KEY_ID") or aws_settings.access_key_id
        secret_key = os.getenv("S3_SECRET_ACCESS_KEY") or aws_settings.secret_access_key
        resolved_region = region or os.getenv("S3_REGION") or aws_settings.resolved_region

        return Aioboto3PayloadStorage(
            bucket=bucket_name,
            region=resolved_region,
            endpoint_url=s3_endpoint,
            access_key_id=access_key,
            secret_access_key=secret_key,
        )
