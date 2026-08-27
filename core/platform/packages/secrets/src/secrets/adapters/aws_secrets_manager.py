import asyncio
import os
import sys
import time
import uuid
from typing import Any

import boto3  # type: ignore[import-untyped]
import structlog
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

logger = structlog.get_logger(__name__)


class AwsSecretsManagerAdapter:
    """
    Adapter for AWS Secrets Manager.
    Uses LocalStack endpoints in development and native IAM in production.
    """

    def __init__(self, secrets_mount_path: str = "/mnt/secrets") -> None:
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

        self._secrets_mount_path = secrets_mount_path
        self._cache: dict[str, tuple[bytes, float]] = {}
        self._cache_ttl_seconds = int(os.getenv("SECRETS_CACHE_TTL", "3600"))
        self._cache_max_size = int(os.getenv("SECRETS_CACHE_MAX_SIZE", "1000"))
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()

    async def _get_lock(self, vault_ref: str) -> asyncio.Lock:
        async with self._locks_lock:
            if vault_ref not in self._locks:
                self._locks[vault_ref] = asyncio.Lock()
            return self._locks[vault_ref]

    async def store_private_key(self, private_key_pem: bytes, category: Any = None) -> str:
        """
        Stores a private key in AWS Secrets Manager and returns the secret name (ARN/Reference).
        """
        # Resolve category string from enum or string
        if category is None:
            category_val = "as2_key"
        elif hasattr(category, "value"):
            category_val = category.value
        else:
            category_val = str(category)

        ref_id = str(uuid.uuid4())
        secret_name = f"edi/{category_val}/{ref_id}"

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

    async def get_secret(self, vault_ref: str) -> str:
        """
        Retrieves a secret from AWS Secrets Manager asynchronously.
        """
        val = await self.retrieve_secret(vault_ref)
        return val.decode("utf-8")

    async def retrieve_secret(self, vault_ref: str) -> bytes:  # noqa: C901
        """
        Retrieves any secret (private key, certificate, or credential).
        Enterprise Hybrid Strategy:
        1. In-Memory TTLCache (Hot path, 0 latency)
        2. Local Sidecar Disk (Warm path, <1ms latency)
        3. AWS Secrets Manager (Cold path fallback, ~100ms latency)
        """
        lock = await self._get_lock(vault_ref)
        async with lock:
            now = time.time()

            # 1. In-Memory Cache
            if vault_ref in self._cache:
                cached_value, expiry = self._cache[vault_ref]
                if now < expiry:
                    return cached_value
                else:
                    # Evict expired entry
                    del self._cache[vault_ref]

            def _execute() -> bytes:
                # Parse vault_ref (e.g. edi/as2_key/1234)
                parts = vault_ref.split("/")

                # Require exactly 3 parts before processing
                if len(parts) != 3:
                    logger.error(
                        "invalid_secret_reference", vault_ref=vault_ref, parts_count=len(parts)
                    )
                    raise ValueError(
                        f"Invalid secret reference format: {vault_ref} (expected 3 parts)"
                    )

                category_str = parts[1]
                ref_id = parts[2]

                local_path = os.path.join(self._secrets_mount_path, category_str, f"{ref_id}.pem")

                # Verify resolved path is within mount directory (path traversal protection)
                resolved_path = os.path.realpath(local_path)
                mount_path = os.path.realpath(self._secrets_mount_path)
                if (
                    not resolved_path.startswith(mount_path + os.sep)
                    and resolved_path != mount_path
                ):
                    logger.error(
                        "path_traversal_attempt_blocked",
                        vault_ref=vault_ref,
                        resolved_path=resolved_path,
                        mount_path=mount_path,
                    )
                    raise ValueError("Invalid vault_ref: path traversal detected")

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

            # Enforce cache size limit by evicting oldest/expired entries
            if len(self._cache) >= self._cache_max_size:
                # Evict expired entries first
                expired_keys = [k for k, (_, exp) in self._cache.items() if now >= exp]
                for k in expired_keys:
                    del self._cache[k]

                # If still over limit, evict oldest entries
                if len(self._cache) >= self._cache_max_size:
                    sorted_entries = sorted(self._cache.items(), key=lambda x: x[1][1])
                    num_to_evict = len(self._cache) - self._cache_max_size + 1
                    for k, _ in sorted_entries[:num_to_evict]:
                        del self._cache[k]

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
        lock = await self._get_lock(vault_ref)
        async with lock:
            self._cache.pop(vault_ref, None)

            def _execute() -> None:
                # Parse vault_ref
                parts = vault_ref.split("/")

                # Require exactly 3 parts before processing
                if len(parts) != 3:
                    logger.error(
                        "invalid_secret_reference_for_deletion",
                        vault_ref=vault_ref,
                        parts_count=len(parts),
                    )
                    raise ValueError(
                        f"Invalid secret reference format: {vault_ref} (expected 3 parts)"
                    )

                category_str = parts[1]
                ref_id = parts[2]

                try:
                    local_path = os.path.join(
                        self._secrets_mount_path, category_str, f"{ref_id}.pem"
                    )
                    resolved_path = os.path.realpath(local_path)
                    mount_path = os.path.realpath(self._secrets_mount_path)

                    if (
                        resolved_path.startswith(mount_path + os.sep) or resolved_path == mount_path
                    ) and os.path.exists(resolved_path):
                        os.remove(resolved_path)
                except OSError as e:
                    logger.warning(
                        "failed_to_delete_local_secret", vault_ref=vault_ref, error=str(e)
                    )

                try:
                    self.client.delete_secret(SecretId=vault_ref, ForceDeleteWithoutRecovery=True)
                except Exception as e:
                    logger.exception("failed_to_delete_secret", error=str(e))
                    raise

            await asyncio.to_thread(_execute)
