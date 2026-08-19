import asyncio
import os
import sys
import time
import uuid

import boto3  # type: ignore
import structlog
from botocore.exceptions import ClientError  # type: ignore
from config.constants import SecretCategory
from config.settings import get_settings

logger = structlog.get_logger(__name__)


class AwsSecretsManagerAdapter:
    """
    Adapter for AWS Secrets Manager. Replaces HashiCorp Vault.
    Uses LocalStack endpoints in development and native IAM in production.
    """

    def __init__(self) -> None:
        env = os.getenv("ENVIRONMENT", "production")
        if env in ("development", "dev", "test", "local") or "pytest" in sys.modules:
            endpoint_url = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
            self.client = boto3.client(
                "secretsmanager",
                endpoint_url=endpoint_url,
                region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
            )
        else:
            self.client = boto3.client(
                "secretsmanager", region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1")
            )

        self._cache: dict[str, tuple[bytes, float]] = {}
        self._cache_ttl_seconds = int(os.getenv("SECRETS_CACHE_TTL", "3600"))

    async def store_private_key(
        self, private_key_pem: bytes, category: SecretCategory | None = None
    ) -> str:
        """
        Stores a private key in AWS Secrets Manager and returns the secret name (ARN/Reference).
        """
        if category is None:
            category = SecretCategory.AS2_KEY

        ref_id = str(uuid.uuid4())
        secret_name = f"edi/{category.value}/{ref_id}"

        def _execute() -> str:
            try:
                self.client.create_secret(
                    Name=secret_name, SecretString=private_key_pem.decode("utf-8")
                )
            except ClientError as e:
                if e.response["Error"]["Code"] == "ResourceExistsException":
                    self.client.update_secret(
                        SecretId=secret_name, SecretString=private_key_pem.decode("utf-8")
                    )
                else:
                    logger.exception("failed_to_store_secret", error=str(e))
                    raise
            return secret_name

        return await asyncio.to_thread(_execute)

    async def retrieve_secret(self, vault_ref: str, field: str | None = None) -> bytes:
        """
        Retrieves any secret (private key, certificate, or credential).
        Enterprise Hybrid Strategy:
        1. In-Memory TTLCache (Hot path, 0 latency)
        2. Local Sidecar Disk (Warm path, <1ms latency)
        3. AWS Secrets Manager (Cold path fallback, ~100ms latency)
        """
        now = time.time()

        # 1. In-Memory Cache
        if vault_ref in self._cache:
            cached_value, expiry = self._cache[vault_ref]
            if now < expiry:
                return cached_value

        def _execute() -> bytes:
            settings = get_settings()
            from config.constants import SecretCategory

            # Parse vault_ref (e.g. edi/as2_key/1234)
            parts = vault_ref.split("/")
            category_str = parts[1] if len(parts) >= 3 else ""
            ref_id = parts[2] if len(parts) >= 3 else vault_ref

            try:
                # Validate that the category matches our architectural constants
                _ = SecretCategory(category_str)
            except ValueError:
                # Log a warning if we encounter an unknown category pattern
                logger.warning("unknown_secret_category", category=category_str)

            local_path = os.path.join(settings.secrets.mount_path, category_str, f"{ref_id}.pem")

            # 2. Local Sidecar Disk
            if os.path.exists(local_path):
                try:
                    with open(local_path, "rb") as lf:
                        return lf.read()
                except OSError as e:
                    logger.warning("failed_to_read_local_secret", path=local_path, error=str(e))

            # 3. AWS Secrets Manager Fallback
            try:
                response = self.client.get_secret_value(SecretId=vault_ref)
                secret_string: str = str(response.get("SecretString", ""))
                if not secret_string:
                    raise ValueError("SecretString is empty")
                return secret_string.encode("utf-8")
            except Exception as e:
                logger.exception("failed_to_retrieve_secret_from_aws", error=str(e))
                raise

        secret_bytes = await asyncio.to_thread(_execute)
        self._cache[vault_ref] = (secret_bytes, now + self._cache_ttl_seconds)
        return secret_bytes

    async def retrieve_private_key(self, vault_ref: str) -> bytes:
        """
        Retrieves a private key from AWS Secrets Manager.
        Delegates to retrieve_secret() — kept for backward compatibility with older interfaces.
        """
        return await self.retrieve_secret(vault_ref)

    async def delete_secret(self, vault_ref: str) -> None:
        """
        Deletes a secret from AWS Secrets Manager immediately.
        """
        self._cache.pop(vault_ref, None)

        def _execute() -> None:
            try:
                self.client.delete_secret(SecretId=vault_ref, ForceDeleteWithoutRecovery=True)
            except Exception as e:
                logger.exception("failed_to_delete_secret", error=str(e))

        await asyncio.to_thread(_execute)
