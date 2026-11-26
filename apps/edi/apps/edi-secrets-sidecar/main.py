import asyncio
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol, cast

import boto3
import structlog
from edi.config.constants import SecretCategory
from secret_store import (
    PlatformSecretStoreSettings,
    atomic_write_secure_file,
    ensure_secure_directory,
)
from seedwork.infra.config import load_settings_safely
from seedwork.infra.config_models import PlatformAwsSettings

logger = structlog.get_logger(__name__)

_DEFAULT_FILTER_PREFIX = "edi/"


def _load_sidecar_settings() -> PlatformSecretStoreSettings:
    return load_settings_safely(PlatformSecretStoreSettings)


class PaginatorProtocol(Protocol):
    def paginate(self, **kwargs: object) -> Iterable[dict[str, object]]: ...


class SecretsManagerClient(Protocol):
    def get_paginator(self, operation_name: str) -> PaginatorProtocol: ...
    def get_secret_value(
        self,
        *,
        SecretId: str,
        VersionId: str | None = None,
        VersionStage: str | None = None,
    ) -> dict[str, str]: ...


def get_client(aws_settings: PlatformAwsSettings | None = None) -> SecretsManagerClient:
    resolved_aws = aws_settings or load_settings_safely(PlatformAwsSettings)
    client_kwargs: dict[str, str] = {"region_name": resolved_aws.resolved_region}
    if resolved_aws.endpoint_url:
        client_kwargs["endpoint_url"] = resolved_aws.endpoint_url
    if resolved_aws.access_key_id:
        client_kwargs["aws_access_key_id"] = resolved_aws.access_key_id
    if resolved_aws.secret_access_key:
        client_kwargs["aws_secret_access_key"] = resolved_aws.secret_access_key
    return cast(SecretsManagerClient, boto3.client("secretsmanager", **client_kwargs))


def _process_secret(
    client: SecretsManagerClient,
    secret: dict[str, object],
    *,
    secrets_mount_path: str,
) -> str | None:
    secret_name = str(secret.get("Name", ""))
    if not secret_name:
        return None
    response = client.get_secret_value(SecretId=secret_name)
    secret_string = response.get("SecretString")
    if not secret_string:
        return None

    parts = secret_name.strip("/").split("/")
    if len(parts) == 2:
        category_str, ref_id = parts[0], parts[1]
    elif len(parts) == 3:
        category_str, ref_id = parts[1], parts[2]
    else:
        logger.debug(
            "ignoring_non_certificate_secret",
            secret_name=secret_name,
            parts_count=len(parts),
        )
        return None

    try:
        SecretCategory(category_str)
    except ValueError:
        logger.error("unknown_secret_category", category=category_str)
        return None

    file_path = os.path.join(secrets_mount_path, *parts)
    resolved_path = Path(file_path).resolve()
    resolved_mount = Path(secrets_mount_path).resolve()
    if not resolved_path.is_relative_to(resolved_mount):
        logger.error(
            "secret_file_path_traversal_prevented",
            secret_name=secret_name,
            file_path=str(resolved_path),
            mount_path=str(resolved_mount),
        )
        return None

    atomic_write_secure_file(resolved_path, secret_string.encode("utf-8"))

    logger.info("secret_updated", secret_id=ref_id, category=category_str)
    return os.path.realpath(file_path)


def _reconcile_files(
    active_files: set[str],
    *,
    secrets_mount_path: str,
    target_dir: str | None = None,
) -> None:
    mount_path = os.path.realpath(secrets_mount_path)
    reconcile_dir = os.path.realpath(target_dir) if target_dir else mount_path

    if not Path(reconcile_dir).is_relative_to(Path(mount_path)):
        logger.error(
            "reconciliation_path_traversal_prevented",
            target_dir=target_dir,
            mount_path=mount_path,
        )
        return

    if not os.path.exists(reconcile_dir):
        return

    for root, _, files in os.walk(reconcile_dir):
        for filename in files:
            if filename.endswith(".tmp"):
                continue
            local_file = os.path.realpath(os.path.join(root, filename))
            if local_file not in active_files:
                try:
                    os.remove(local_file)
                    logger.info("removed_revoked_secret_file", path=local_file)
                except OSError as e:
                    logger.error(
                        "failed_to_remove_revoked_secret_file",
                        path=local_file,
                        error=str(e),
                    )


def sync_secrets(settings: PlatformSecretStoreSettings | None = None) -> None:
    resolved_settings = settings or _load_sidecar_settings()
    if not resolved_settings.backend.requires_sync_sidecar:
        ensure_secure_directory(Path(resolved_settings.mount_path))
        logger.info(
            "secrets_sync_managed_by_sovereign_backend",
            backend=resolved_settings.backend.value,
            mount_path=resolved_settings.mount_path,
        )
        return

    aws_settings = load_settings_safely(PlatformAwsSettings)
    resolved_settings.validate_against_aws(aws_settings)
    client = get_client(aws_settings)
    try:
        paginator = client.get_paginator("list_secrets")
        filter_prefix = resolved_settings.filter_prefix or _DEFAULT_FILTER_PREFIX
        prefix_parts = [p for p in filter_prefix.strip("/").split("/") if p]

        if prefix_parts:
            filters = [{"Key": "name", "Values": [filter_prefix]}]
            page_iterator = paginator.paginate(Filters=filters)
            reconcile_target = os.path.join(resolved_settings.mount_path, *prefix_parts)
        else:
            page_iterator = paginator.paginate()
            reconcile_target = resolved_settings.mount_path

        active_files: set[str] = set()

        for page in page_iterator:
            secret_list = page.get("SecretList")
            if isinstance(secret_list, list):
                for secret in secret_list:
                    if isinstance(secret, dict):
                        file_path = _process_secret(
                            client,
                            secret,
                            secrets_mount_path=resolved_settings.mount_path,
                        )
                        if file_path:
                            active_files.add(file_path)

        _reconcile_files(
            active_files,
            secrets_mount_path=resolved_settings.mount_path,
            target_dir=reconcile_target,
        )

        logger.info("secrets_sync_completed", mount_path=resolved_settings.mount_path)
    except Exception as e:
        logger.exception("secrets_sync_failed", error=str(e))


async def async_main() -> None:
    settings = _load_sidecar_settings()
    logger.info(
        "starting_secrets_sidecar",
        backend=settings.backend.value,
        mount_path=settings.mount_path,
        sync_interval_seconds=settings.sync_interval_seconds,
    )
    ensure_secure_directory(Path(settings.mount_path))

    while True:
        await asyncio.to_thread(sync_secrets, settings)
        await asyncio.sleep(settings.sync_interval_seconds)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
