import asyncio
import os
from contextlib import suppress
from typing import Any, Protocol, cast

import boto3  # type: ignore[import-untyped]
import structlog
from edi.config.constants import SecretCategory
from edi.config.settings import get_settings

logger = structlog.get_logger(__name__)

settings = get_settings()
SECRETS_MOUNT_PATH = settings.secrets.mount_path
POLL_INTERVAL_SECONDS = settings.secrets.sync_interval_seconds


class SecretsManagerClient(Protocol):
    def get_paginator(self, operation_name: str) -> Any: ...
    def get_secret_value(self, *, SecretId: str) -> dict[str, str]: ...


def get_client() -> SecretsManagerClient:
    env = os.getenv("ENVIRONMENT", "production")
    if env in ("development", "dev", "test", "local"):
        endpoint_url = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
        return cast(
            SecretsManagerClient,
            boto3.client(
                "secretsmanager",
                endpoint_url=endpoint_url,
                region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
            ),
        )
    else:
        return cast(
            SecretsManagerClient,
            boto3.client(
                "secretsmanager", region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1")
            ),
        )


def _process_secret(client: SecretsManagerClient, secret: dict[str, Any]) -> str | None:
    secret_name = secret["Name"]
    response = client.get_secret_value(SecretId=secret_name)
    secret_string = response.get("SecretString")
    if not secret_string:
        return None

    parts = secret_name.split("/")
    if len(parts) != 3:
        logger.warning(
            "invalid_secret_name_format",
            secret_name=secret_name,
            parts_count=len(parts),
        )
        return None

    category_str = parts[1]
    ref_id = parts[2]

    try:
        validated_category = SecretCategory(category_str)
    except ValueError:
        logger.warning("unknown_secret_category", category=category_str)
        return None

    file_path = os.path.join(SECRETS_MOUNT_PATH, validated_category.value, f"{ref_id}.pem")
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


def _reconcile_files(active_files: set[str]) -> None:
    mount_path = os.path.realpath(SECRETS_MOUNT_PATH)
    for root, _, files in os.walk(mount_path):
        for filename in files:
            if filename.endswith(".pem"):
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
        page_iterator = paginator.paginate(Filters=[{"Key": "name", "Values": ["edi/"]}])

        active_files: set[str] = set()

        for page in page_iterator:
            for secret in page.get("SecretList", []):
                file_path = _process_secret(client, secret)
                if file_path:
                    active_files.add(file_path)

        _reconcile_files(active_files)

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
