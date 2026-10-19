"""Adapter for AWS Secrets Manager and mounted secrets directory."""

import asyncio
import os
import time
from pathlib import Path
from typing import Protocol

import boto3
import structlog
from botocore.exceptions import ClientError
from seedwork.id_registry import SystemIdPrefix
from seedwork.infra.config_models import PlatformAwsSettings
from seedwork.utils import generate_id

from secret_store.ports.secret_path_resolver_port import MountedSecretPathResolverPort
from secret_store.ports.secret_store_port import SecretStorePort

logger = structlog.get_logger(__name__)


class SecretsManagerClientProtocol(Protocol):
    """Protocol for interacting with the AWS Secrets Manager client."""

    def create_secret(
        self, *, Name: str, SecretString: str, Description: str = ...
    ) -> dict[str, object]: ...

    def get_secret_value(self, *, SecretId: str) -> dict[str, object]: ...

    def delete_secret(
        self, *, SecretId: str, RecoveryWindowInDays: int = 7
    ) -> dict[str, object]: ...


class AwsSecretsManagerAdapter(SecretStorePort):
    """Adapter for AWS Secrets Manager.

    Uses LocalStack endpoints when configured and native IAM in production.
    Supports reading from local volume mounts at /mnt/secrets for high-throughput reads.
    """

    def __init__(
        self,
        endpoint_url: str | None = None,
        region_name: str | None = None,
        secrets_mount_path: str = "/mnt/secrets",
        client: SecretsManagerClientProtocol | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        secrets_prefix: str | None = None,
        path_resolver: MountedSecretPathResolverPort | None = None,
        aws_settings: PlatformAwsSettings | None = None,
    ) -> None:
        if client is not None:
            self.client: SecretsManagerClientProtocol = client
        else:
            settings = aws_settings or PlatformAwsSettings()
            resolved_endpoint = endpoint_url or settings.endpoint_url
            resolved_region = region_name or settings.resolved_region

            client_kwargs: dict[str, str] = {"region_name": resolved_region}
            if resolved_endpoint:
                client_kwargs["endpoint_url"] = resolved_endpoint

            access_key = aws_access_key_id or settings.access_key_id
            secret_key = aws_secret_access_key or settings.secret_access_key
            if access_key:
                client_kwargs["aws_access_key_id"] = access_key
            if secret_key:
                client_kwargs["aws_secret_access_key"] = secret_key

            self.client = boto3.client("secretsmanager", **client_kwargs)
        self._secrets_mount_path = secrets_mount_path
        self._secrets_prefix = (
            secrets_prefix if secrets_prefix is not None else os.getenv("SECRETS_PREFIX", "")
        )
        self._path_resolver: MountedSecretPathResolverPort | None = path_resolver
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

    async def store_private_key(self, private_key_pem: bytes, category: str | None = None) -> str:
        category_val = category if category else "keys"
        secret_id = generate_id(SystemIdPrefix.GENERIC)
        prefix = f"{self._secrets_prefix}/" if self._secrets_prefix else ""
        secret_name = f"{prefix}{category_val}/{secret_id}"
        private_key_str = private_key_pem.decode("utf-8")

        await asyncio.to_thread(
            self.client.create_secret,
            Name=secret_name,
            SecretString=private_key_str,
            Description=f"Managed private key for {category_val}",
        )
        return secret_name

    async def _fetch_from_aws(self, vault_ref: str) -> bytes:
        try:
            response = await asyncio.to_thread(self.client.get_secret_value, SecretId=vault_ref)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            msg = str(e.response.get("Error", {}).get("Message", ""))
            if code == "ResourceNotFoundException" or (
                code == "InvalidRequestException" and "marked for deletion" in msg.lower()
            ):
                raise ValueError(f"Secret not found: {vault_ref}") from e
            raise

        secret_str = response.get("SecretString")
        if secret_str is not None:
            return str(secret_str).encode("utf-8")
        secret_bin = response.get("SecretBinary")
        if secret_bin is not None:
            if isinstance(secret_bin, bytes):
                return secret_bin
            if isinstance(secret_bin, (bytearray, memoryview)):
                return bytes(secret_bin)
            if isinstance(secret_bin, str):
                return secret_bin.encode("utf-8")
        raise ValueError(f"Secret value is empty: {vault_ref}")

    async def retrieve_secret(self, vault_ref: str) -> bytes:
        cached = self._cache.get(vault_ref)
        if cached is not None and time.time() < cached[1]:
            return cached[0]

        lock = await self._get_lock(vault_ref)
        async with lock:
            cached = self._cache.get(vault_ref)
            if cached is not None and time.time() < cached[1]:
                return cached[0]

            mounted_path = self._resolve_mounted_path(vault_ref)
            if mounted_path is not None and mounted_path.is_file():
                val = await asyncio.to_thread(self._read_file, str(mounted_path))
            else:
                val = await self._fetch_from_aws(vault_ref)

            if len(self._cache) >= self._cache_max_size:
                self._cache.clear()
            self._cache[vault_ref] = (val, time.time() + self._cache_ttl_seconds)
            return val

    def _resolve_mounted_path(self, vault_ref: str) -> Path | None:
        """Resolves and validates that a candidate secret path remains securely within _secrets_mount_path.

        Delegates path resolution to the injected MountedSecretPathResolverPort strategy.
        """
        if self._path_resolver is None:
            return None
        try:
            mount_root = Path(self._secrets_mount_path).resolve()
            return self._path_resolver.resolve(mount_root, vault_ref)
        except (ValueError, OSError, RuntimeError):
            return None

    @staticmethod
    def _read_file(path: str) -> bytes:
        with open(path, "rb") as f:
            return f.read()

    async def get_secret(self, vault_ref: str) -> str:
        b = await self.retrieve_secret(vault_ref)
        return b.decode("utf-8")

    async def retrieve_private_key(self, vault_ref: str) -> bytes:
        return await self.retrieve_secret(vault_ref)

    async def delete_secret(self, vault_ref: str) -> None:
        async with self._locks_lock:
            self._locks.pop(vault_ref, None)
        self._cache.pop(vault_ref, None)

        # Remove local sidecar file if present
        mounted_path = self._resolve_mounted_path(vault_ref)
        if mounted_path is not None and mounted_path.is_file():
            try:
                await asyncio.to_thread(mounted_path.unlink, missing_ok=True)
            except OSError as e:
                logger.warning(
                    "local_secret_file_removal_failed",
                    vault_ref=vault_ref,
                    error=str(e),
                )

        try:
            await asyncio.to_thread(
                self.client.delete_secret,
                SecretId=vault_ref,
                RecoveryWindowInDays=7,
            )
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            msg = str(e.response.get("Error", {}).get("Message", ""))
            if code == "ResourceNotFoundException" or (
                code == "InvalidRequestException" and "marked for deletion" in msg.lower()
            ):
                return
            raise
