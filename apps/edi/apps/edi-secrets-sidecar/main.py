import asyncio
import os
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol, cast

import boto3
import structlog
from edi.config.constants import SecretCategory

logger = structlog.get_logger(__name__)

SECRETS_MOUNT_PATH = os.environ.get("SECRETS_MOUNT_PATH", "/mnt/secrets")
POLL_INTERVAL_SECONDS = int(os.environ.get("SECRETS_SYNC_INTERVAL_SECONDS", "300"))
if POLL_INTERVAL_SECONDS <= 0:
    raise ValueError("SECRETS_SYNC_INTERVAL_SECONDS must be strictly positive.")


class SecretsManagerClient(Protocol):
    def get_paginator(self, operation_name: str) -> Any: ...
    def get_secret_value(
        self,
        *,
        SecretId: str,
        VersionId: str | None = None,
        VersionStage: str | None = None,
    ) -> dict[str, str]: ...


def get_client() -> SecretsManagerClient:
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    client_kwargs: dict[str, str] = {"region_name": region}
    endpoint_url = os.getenv("AWS_ENDPOINT_URL")
    if endpoint_url:
        client_kwargs["endpoint_url"] = endpoint_url
    access_key = os.getenv("AWS_ACCESS_KEY_ID")
    if access_key:
        client_kwargs["aws_access_key_id"] = access_key
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    if secret_key:
        client_kwargs["aws_secret_access_key"] = secret_key
    return cast(SecretsManagerClient, boto3.client("secretsmanager", **client_kwargs))


def _process_secret(client: SecretsManagerClient, secret: dict[str, Any]) -> str | None:
    secret_name = secret["Name"]
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
        logger.warning("unknown_secret_category", category=category_str)
        return None

    file_path = os.path.join(SECRETS_MOUNT_PATH, *parts)
    resolved_path = Path(file_path).resolve()
    resolved_mount = Path(SECRETS_MOUNT_PATH).resolve()
    if not resolved_path.is_relative_to(resolved_mount):
        logger.error(
            "secret_file_path_traversal_prevented",
            secret_name=secret_name,
            file_path=str(resolved_path),
            mount_path=str(resolved_mount),
        )
        return None

    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    tmp_path = file_path + ".tmp"
    rename_succeeded = False
    try:
        with open(tmp_path, "w") as f:
            f.write(secret_string)
        os.rename(tmp_path, file_path)
        rename_succeeded = True
    finally:
        if not rename_succeeded:
            with suppress(OSError):
                os.remove(tmp_path)

    logger.info("secret_updated", secret_id=ref_id, category=category_str)
    return os.path.realpath(file_path)


def _reconcile_files(active_files: set[str], target_dir: str | None = None) -> None:
    mount_path = os.path.realpath(SECRETS_MOUNT_PATH)
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
                    logger.warning(
                        "failed_to_remove_revoked_secret_file",
                        path=local_file,
                        error=str(e),
                    )


def sync_secrets() -> None:
    client = get_client()
    try:
        paginator = client.get_paginator("list_secrets")
        filter_prefix = os.environ.get("SECRETS_FILTER_PREFIX", "edi/").strip()
        prefix_parts = [p for p in filter_prefix.strip("/").split("/") if p]

        if prefix_parts:
            filters = [{"Key": "name", "Values": [filter_prefix]}]
            page_iterator = paginator.paginate(Filters=filters)
            reconcile_target = os.path.join(SECRETS_MOUNT_PATH, *prefix_parts)
        else:
            page_iterator = paginator.paginate()
            reconcile_target = SECRETS_MOUNT_PATH

        active_files: set[str] = set()

        for page in page_iterator:
            for secret in page.get("SecretList", []):
                file_path = _process_secret(client, secret)
                if file_path:
                    active_files.add(file_path)

        _reconcile_files(active_files, target_dir=reconcile_target)

        logger.info("secrets_sync_completed", mount_path=SECRETS_MOUNT_PATH)
    except Exception as e:
        logger.exception("secrets_sync_failed", error=str(e))


async def async_main() -> None:
    logger.info("starting_secrets_sidecar")
    os.makedirs(SECRETS_MOUNT_PATH, exist_ok=True)

    while True:
        await asyncio.to_thread(sync_secrets)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
