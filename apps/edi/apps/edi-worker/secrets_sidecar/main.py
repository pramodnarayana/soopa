import asyncio
import os

import boto3  # type: ignore
import structlog
from config.settings import get_settings

logger = structlog.get_logger(__name__)

settings = get_settings()
SECRETS_MOUNT_PATH = settings.secrets.mount_path
POLL_INTERVAL_SECONDS = settings.secrets.sync_interval_seconds


from typing import Any


def get_client() -> Any:
    env = os.getenv("ENVIRONMENT", "production")
    if env in ("development", "dev", "test", "local"):
        endpoint_url = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
        return boto3.client(
            "secretsmanager",
            endpoint_url=endpoint_url,
            region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
        )
    else:
        return boto3.client(
            "secretsmanager", region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        )


def sync_secrets() -> None:
    client = get_client()
    try:
        # Fetch all secrets starting with 'edi/'
        # In a real environment with thousands, we'd use pagination
        paginator = client.get_paginator("list_secrets")
        page_iterator = paginator.paginate(Filters=[{"Key": "name", "Values": ["edi/"]}])

        for page in page_iterator:
            for secret in page.get("SecretList", []):
                secret_name = secret["Name"]

                # Fetch secret value
                response = client.get_secret_value(SecretId=secret_name)
                secret_string = response.get("SecretString")
                if not secret_string:
                    continue

                # Format is usually edi/{category}/{id}
                parts = secret_name.split("/")
                if len(parts) >= 3:
                    category_str = parts[1]
                    ref_id = parts[2]
                    from config.constants import SecretCategory

                    try:
                        # Validate that the category matches our architectural constants
                        _ = SecretCategory(category_str)
                    except ValueError:
                        # Log a warning if we encounter an unknown category pattern
                        logger.warning("unknown_secret_category", category=category_str)

                    file_path = os.path.join(SECRETS_MOUNT_PATH, category_str, f"{ref_id}.pem")
                    os.makedirs(os.path.dirname(file_path), exist_ok=True)

                    # Write file atomically
                    tmp_path = file_path + ".tmp"
                    with open(tmp_path, "w") as f:
                        f.write(secret_string)
                    os.rename(tmp_path, file_path)

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
