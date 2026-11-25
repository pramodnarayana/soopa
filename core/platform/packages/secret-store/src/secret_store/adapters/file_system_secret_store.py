"""Local and Kubernetes mounted filesystem secret store adapter."""

from __future__ import annotations

import asyncio
import contextlib
import os
import weakref
from pathlib import Path

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


class FileSystemSecretStoreAdapter(SecretStorePort):
    """Sovereign secret store adapter reading and writing secrets to a local or mounted volume (Kubernetes Secrets / Docker)."""

    def __init__(
        self,
        secrets_mount_path: str = "/mnt/secrets",
        secrets_prefix: str | None = None,
        path_resolver: MountedSecretPathResolverPort | None = None,
    ) -> None:
        self._secrets_mount_path = Path(secrets_mount_path).resolve()
        if not self._secrets_mount_path.exists():
            self._secrets_mount_path.mkdir(parents=True, exist_ok=True)
        self._secrets_prefix = (
            secrets_prefix if secrets_prefix is not None else os.getenv("SECRETS_PREFIX", "")
        ).strip("/")
        self._path_resolver = path_resolver
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
        self._locks_lock = asyncio.Lock()

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
        """Stores a private key on the filesystem and returns its reference path."""
        category_name = (category if category else DEFAULT_KEY_CATEGORY).strip("/")
        key_id = generate_id(SystemIdPrefix.GENERIC)
        relative_path = (
            f"{self._secrets_prefix}/{category_name}/{key_id}"
            if self._secrets_prefix
            else f"{category_name}/{key_id}"
        )
        target_path = self._resolve_mounted_path(relative_path)
        if target_path is None:
            raise ValueError(f"Invalid secret path reference: {relative_path}")

        lock = await self._get_lock(relative_path)
        async with lock:
            await asyncio.to_thread(self._atomic_write_key, target_path, private_key_pem)

        logger.info("secret_stored_on_filesystem", path=str(target_path), ref=relative_path)
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
        """Retrieves any secret (private key, certificate, or credential) from the filesystem."""
        target_path = self._resolve_mounted_path(vault_ref)
        if target_path is None or not target_path.is_file():
            raise ValueError(f"Secret not found: {vault_ref}")

        lock = await self._get_lock(vault_ref)
        async with lock:
            val = await asyncio.to_thread(target_path.read_bytes)
            if not val:
                raise ValueError(f"Secret value is empty: {vault_ref}")
            return val

    async def retrieve_private_key(self, vault_ref: str) -> bytes:
        """Retrieves a private key from the filesystem."""
        return await self.retrieve_secret(vault_ref)

    async def delete_secret(self, vault_ref: str) -> None:
        """Deletes a secret reference from the filesystem."""
        async with self._locks_lock:
            self._locks.pop(vault_ref, None)

        target_path = self._resolve_mounted_path(vault_ref)
        if target_path is not None and target_path.is_file():
            await asyncio.to_thread(target_path.unlink, missing_ok=True)
            logger.info("secret_deleted_from_filesystem", ref=vault_ref)
