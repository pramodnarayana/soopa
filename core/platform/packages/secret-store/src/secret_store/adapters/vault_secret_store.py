"""HashiCorp Vault / OpenBao secret store adapter."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import weakref
from pathlib import Path

import httpx
import structlog
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id

from secret_store.ports.secret_path_resolver_port import MountedSecretPathResolverPort
from secret_store.ports.secret_store_port import (
    Category,
    SecretStorePort,
    normalize_prefixed_category_ref,
)

logger = structlog.get_logger(__name__)

DEFAULT_KEY_CATEGORY = "keys"
DEFAULT_VAULT_MOUNT_POINT = "secret"
DEFAULT_VAULT_ADDR = "http://127.0.0.1:8200"
VAULT_ADDR_ENV = "VAULT_ADDR"
VAULT_TOKEN_ENV = "VAULT_TOKEN"  # noqa: S105 - Environment variable name for Vault token, not a hardcoded secret
VAULT_MOUNT_POINT_ENV = "VAULT_MOUNT_POINT"
SECRETS_PREFIX_ENV = "SECRETS_PREFIX"
VAULT_TOKEN_HEADER = "X-Vault-Token"  # noqa: S105 - Standard HashiCorp Vault HTTP header name, not a hardcoded secret
HTTP_STATUS_NOT_FOUND = 404


class VaultSecretStoreAdapter(SecretStorePort):
    """Adapter for HashiCorp Vault / OpenBao KV v2 secrets engine with pooled HTTP and local mount caching."""

    def __init__(
        self,
        vault_url: str | None = None,
        vault_token: str | None = None,
        mount_point: str = DEFAULT_VAULT_MOUNT_POINT,
        secrets_mount_path: str = "/mnt/secrets",
        secrets_prefix: str | None = None,
        path_resolver: MountedSecretPathResolverPort | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._vault_url = (vault_url or os.getenv(VAULT_ADDR_ENV) or DEFAULT_VAULT_ADDR).rstrip("/")
        self._vault_token = (
            vault_token if vault_token is not None else os.getenv(VAULT_TOKEN_ENV, "")
        )
        self._mount_point = (os.getenv(VAULT_MOUNT_POINT_ENV) or mount_point).strip("/")
        self._secrets_mount_path = Path(secrets_mount_path).resolve()
        self._secrets_mount_path.mkdir(parents=True, exist_ok=True)
        self._secrets_prefix = (
            secrets_prefix if secrets_prefix is not None else os.getenv(SECRETS_PREFIX_ENV, "")
        ).strip("/")
        self._path_resolver = path_resolver
        self._http_transport = http_transport
        self._timeout_seconds = timeout_seconds
        self._http_client: httpx.AsyncClient | None = None
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
        self._locks_lock = asyncio.Lock()

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                transport=self._http_transport,
                timeout=self._timeout_seconds,
            )
        return self._http_client

    async def aclose(self) -> None:
        """Closes the underlying pooled HTTP client cleanly."""
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    async def _get_lock(self, vault_ref: str) -> asyncio.Lock:
        async with self._locks_lock:
            lock = self._locks.get(vault_ref)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[vault_ref] = lock
            return lock

    def normalize_category_ref(self, vault_ref: str, category: Category) -> str | None:
        return normalize_prefixed_category_ref(
            vault_ref,
            category=category,
            secrets_prefix=self._secrets_prefix,
        )

    def _resolve_mounted_path(self, vault_ref: str) -> Path | None:
        if self._path_resolver is None:
            return None
        clean_ref = vault_ref.strip().removeprefix("vault://").strip("/")
        if not clean_ref:
            return None
        try:
            return self._path_resolver.resolve(self._secrets_mount_path, clean_ref)
        except (ValueError, OSError, RuntimeError):
            return None

    async def get_secret(self, vault_ref: str) -> str:
        """Fetch a secret string given its reference path."""
        secret_bytes = await self.retrieve_secret(vault_ref)
        return secret_bytes.decode("utf-8")

    async def store_private_key(
        self, private_key_pem: bytes, category: Category | None = None
    ) -> str:
        """Stores a private key in Vault KV v2 and syncs to local mount."""
        category_name = (category if category else DEFAULT_KEY_CATEGORY).strip("/")
        key_id = generate_id(SystemIdPrefix.GENERIC)
        relative_path = (
            f"{self._secrets_prefix}/{category_name}/{key_id}"
            if self._secrets_prefix
            else f"{category_name}/{key_id}"
        )

        lock = await self._get_lock(relative_path)
        async with lock:
            if not self._vault_token:
                logger.error("vault_secret_store_missing_token", ref=relative_path)
                raise ValueError(
                    "VAULT_TOKEN is required to store secrets in HashiCorp Vault / OpenBao."
                )
            url = f"{self._vault_url}/v1/{self._mount_point}/data/{relative_path}"
            headers = {VAULT_TOKEN_HEADER: self._vault_token}
            payload: dict[str, dict[str, str]] = {
                "data": {"value": private_key_pem.decode("utf-8")}
            }
            client = self._get_http_client()
            resp = await client.post(url, headers=headers, json=payload)
            if resp.is_error:
                logger.error(
                    "vault_secret_store_failed",
                    ref=relative_path,
                    status_code=resp.status_code,
                )
                raise RuntimeError(
                    f"Vault store failed for '{relative_path}' with HTTP {resp.status_code}"
                )

            target_path = self._resolve_mounted_path(relative_path)
            if target_path is not None:
                await asyncio.to_thread(self._atomic_write_key, target_path, private_key_pem)

        logger.info("secret_stored_in_vault", ref=relative_path)
        return relative_path

    @staticmethod
    def _atomic_write_key(target_path: Path, data: bytes) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.with_name(
            f".{target_path.name}.{os.getpid()}.{os.urandom(6).hex()}.tmp"
        )
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        written = False
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, target_path)
            written = True
        finally:
            if not written:
                with contextlib.suppress(OSError):
                    temp_path.unlink(missing_ok=True)

    async def retrieve_secret(self, vault_ref: str) -> bytes:
        """Retrieves a secret from local volume mount or Vault API."""
        clean_ref = vault_ref.strip().removeprefix("vault://").strip("/")
        local_path = self._resolve_mounted_path(clean_ref)

        # 1. Check local mount cache first (e.g. populated by Vault Agent)
        if local_path is not None and await asyncio.to_thread(local_path.is_file):
            lock = await self._get_lock(clean_ref)
            async with lock:
                val = await asyncio.to_thread(local_path.read_bytes)
                if not val:
                    raise ValueError(f"Secret value is empty: {vault_ref}")
                return val

        # 2. Fetch from Vault API
        if not self._vault_token:
            raise ValueError(f"Secret not found: {vault_ref}")

        url = f"{self._vault_url}/v1/{self._mount_point}/data/{clean_ref}"
        headers = {VAULT_TOKEN_HEADER: self._vault_token}
        client = self._get_http_client()
        resp = await client.get(url, headers=headers)
        if resp.status_code == HTTP_STATUS_NOT_FOUND:
            raise ValueError(f"Secret not found: {vault_ref}")
        if resp.is_error:
            logger.error(
                "vault_secret_retrieve_failed",
                ref=clean_ref,
                status_code=resp.status_code,
            )
            raise RuntimeError(
                f"Vault retrieve failed for '{clean_ref}' with HTTP {resp.status_code}"
            )

        body: object = resp.json()
        outer_data = body.get("data") if isinstance(body, dict) else None
        inner_data = outer_data.get("data") if isinstance(outer_data, dict) else None
        if not isinstance(inner_data, dict) or not inner_data:
            raise ValueError(f"Secret value is empty: {vault_ref}")
        raw_val = inner_data.get("value")
        if isinstance(raw_val, str):
            if not raw_val:
                raise ValueError(f"Secret value is empty: {vault_ref}")
            return raw_val.encode("utf-8")
        return json.dumps(inner_data).encode("utf-8")

    async def retrieve_private_key(self, vault_ref: str) -> bytes:
        return await self.retrieve_secret(vault_ref)

    async def delete_secret(self, vault_ref: str) -> None:
        clean_ref = vault_ref.strip().removeprefix("vault://").strip("/")
        async with self._locks_lock:
            self._locks.pop(clean_ref, None)

        local_path = self._resolve_mounted_path(clean_ref)
        if local_path is not None and await asyncio.to_thread(local_path.is_file):
            await asyncio.to_thread(local_path.unlink, missing_ok=True)

        if self._vault_token:
            url = f"{self._vault_url}/v1/{self._mount_point}/data/{clean_ref}"
            headers = {VAULT_TOKEN_HEADER: self._vault_token}
            client = self._get_http_client()
            resp = await client.delete(url, headers=headers)
            if resp.status_code != HTTP_STATUS_NOT_FOUND and resp.is_error:
                logger.error(
                    "vault_secret_delete_failed",
                    ref=clean_ref,
                    status_code=resp.status_code,
                )
                raise RuntimeError(
                    f"Vault delete failed for '{clean_ref}' with HTTP {resp.status_code}"
                )
        logger.info("secret_deleted_from_vault", ref=clean_ref)
