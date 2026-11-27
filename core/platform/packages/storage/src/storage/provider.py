"""Universal Platform Composition Root for payload object and file storage."""

from __future__ import annotations

import os
from pathlib import Path

import structlog
from seedwork.infra.config_models import PlatformAwsSettings

from storage.adapters.file_system_storage_adapter import FileSystemPayloadStorage
from storage.adapters.s3_storage_adapter import Aioboto3PayloadStorage
from storage.config import (
    DEFAULT_STORAGE_BUCKET,
    DEFAULT_STORAGE_FILE_PATH,
    PlatformStorageSettings,
)
from storage.domain.enums import StorageBackend
from storage.ports.payload_storage_port import PayloadStoragePort

logger = structlog.get_logger(__name__)


class StorageProvider:
    @staticmethod
    def resolve_backend(
        backend: StorageBackend | str | None = None,
        *,
        base_directory: str | Path | None = None,
    ) -> StorageBackend:
        """Resolves the configured StorageBackend enum from parameter or environment."""
        if isinstance(backend, StorageBackend):
            return backend
        raw = (
            (
                backend
                or os.getenv("STORAGE_BACKEND")
                or (
                    StorageBackend.FILE.value
                    if base_directory
                    or os.getenv("STORAGE_FILE_PATH")
                    or os.getenv("PAYLOAD_STORAGE_PATH")
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
    def from_settings(
        settings: PlatformStorageSettings,
        *,
        aws_settings: PlatformAwsSettings | None = None,
    ) -> PayloadStoragePort:
        """Builds a PayloadStoragePort from validated ``PlatformStorageSettings`` with fail-fast checks."""
        resolved_aws = aws_settings
        if settings.resolved_backend == StorageBackend.S3:
            resolved_aws = aws_settings or PlatformAwsSettings()
            settings.validate_against_aws(resolved_aws)

        return StorageProvider.create_payload_storage(
            bucket=settings.bucket,
            base_directory=settings.resolved_file_path,
            backend=settings.resolved_backend,
            endpoint_url=settings.endpoint_url,
            region=settings.region,
            access_key_id=settings.access_key_id,
            secret_access_key=settings.secret_access_key,
            aws_settings=resolved_aws,
        )

    @staticmethod
    def create_payload_storage(
        bucket: str | None = None,
        base_directory: str | Path | None = None,
        backend: StorageBackend | str | None = None,
        endpoint_url: str | None = None,
        region: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        aws_settings: PlatformAwsSettings | None = None,
    ) -> PayloadStoragePort:
        """Creates a PayloadStoragePort based on environment variables or explicit parameters.

        Supported backends via STORAGE_BACKEND:
        - 'file' / 'filesystem' / 'nfs' / 'posix': Uses FileSystemPayloadStorage on local / shared disk.
        - 's3' / 'minio' (default): Uses Aioboto3PayloadStorage pointing to AWS S3 or on-prem MinIO.
        """
        selected_backend = StorageProvider.resolve_backend(
            backend,
            base_directory=base_directory,
        )
        if selected_backend.is_filesystem:
            mount_path = (
                base_directory
                or os.getenv("PAYLOAD_STORAGE_PATH")
                or os.getenv("STORAGE_FILE_PATH")
                or DEFAULT_STORAGE_FILE_PATH
            )
            logger.info(
                "payload_storage_initialized",
                backend=selected_backend.value,
                base_directory=str(mount_path),
            )
            return FileSystemPayloadStorage(base_directory=mount_path)

        resolved_aws = aws_settings or PlatformAwsSettings()
        bucket_name: str = bucket or os.getenv("S3_BUCKET") or DEFAULT_STORAGE_BUCKET
        s3_endpoint = endpoint_url or os.getenv("S3_ENDPOINT_URL") or resolved_aws.endpoint_url
        access_key = access_key_id or os.getenv("S3_ACCESS_KEY_ID") or resolved_aws.access_key_id
        secret_key = (
            secret_access_key or os.getenv("S3_SECRET_ACCESS_KEY") or resolved_aws.secret_access_key
        )
        resolved_region = region or os.getenv("S3_REGION") or resolved_aws.resolved_region

        logger.info(
            "payload_storage_initialized",
            backend=selected_backend.value,
            bucket=bucket_name,
            region=resolved_region,
            has_custom_endpoint=bool(s3_endpoint),
        )
        return Aioboto3PayloadStorage(
            bucket=bucket_name,
            region=resolved_region,
            endpoint_url=s3_endpoint,
            access_key_id=access_key,
            secret_access_key=secret_key,
        )
