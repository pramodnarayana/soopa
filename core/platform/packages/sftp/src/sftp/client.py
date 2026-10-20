"""Enterprise SFTP client and session manager."""

from __future__ import annotations

import asyncio
import io
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import paramiko
import structlog

from sftp.exceptions import (
    SftpAuthenticationError,
    SftpConnectionError,
    SftpOperationError,
)
from sftp.keys import parse_client_private_key, setup_host_key
from sftp.patches import apply_legacy_algorithm_support
from sftp.policies import DiagnosticHostKeyPolicy
from sftp.security import resolve_and_validate_host

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SftpFileMetadata:
    """Strongly-typed metadata for remote SFTP file entries."""

    filename: str
    size_bytes: int
    modified_at: datetime


@dataclass(frozen=True)
class SftpConnectionConfig:
    """Configuration for establishing an SFTP connection."""

    host: str
    port: int = 22
    username: str = ""
    password: str | None = None
    private_key: str | None = None
    private_key_passphrase: str | None = None
    host_key: str | None = None
    base_directory: str = "/"
    timeout_seconds: float = 15.0
    allow_local: bool = False


def create_ssh_client(
    config: SftpConnectionConfig,
    diagnostic: bool = False,
) -> paramiko.SSHClient:
    """Creates, configures, and connects an enterprise-grade paramiko.SSHClient."""
    resolve_and_validate_host(
        host=config.host,
        port=config.port,
        allow_local=config.allow_local,
    )

    client = paramiko.SSHClient()

    if diagnostic:
        client.set_missing_host_key_policy(DiagnosticHostKeyPolicy())
    else:
        setup_host_key(
            client=client,
            host=config.host,
            port=config.port,
            host_key_string=config.host_key,
        )

    connect_kwargs: dict[str, Any] = {
        "hostname": config.host,
        "port": config.port,
        "username": config.username,
        "look_for_keys": False,
        "allow_agent": False,
        "timeout": config.timeout_seconds,
    }

    if config.host_key and "ssh-rsa" in config.host_key:
        apply_legacy_algorithm_support()

        def legacy_transport_factory(*args: Any, **kwargs: Any) -> paramiko.Transport:
            t = paramiko.Transport(*args, **kwargs)
            if hasattr(t, "_preferred_keys") and "ssh-rsa" not in t._preferred_keys:
                t._preferred_keys = (*t._preferred_keys, "ssh-rsa")
            if hasattr(t, "_key_info") and "ssh-rsa" not in t._key_info:
                t._key_info = dict(t._key_info)
                t._key_info["ssh-rsa"] = paramiko.RSAKey
            return t

        connect_kwargs["transport_factory"] = legacy_transport_factory

    if config.private_key:
        connect_kwargs["pkey"] = parse_client_private_key(
            config.private_key, password=config.private_key_passphrase
        )
    elif config.password:
        connect_kwargs["password"] = config.password
    else:
        raise ValueError("Must provide either a password or private_key for SFTP authentication.")

    try:
        client.connect(**connect_kwargs)
        return client
    except paramiko.AuthenticationException as exc:
        client.close()
        logger.warning("sftp_auth_failed", host=config.host, error=str(exc))
        raise SftpAuthenticationError(f"SFTP authentication failed: {exc}") from exc
    except (paramiko.SSHException, OSError) as exc:
        client.close()
        logger.warning("sftp_connection_failed", host=config.host, error=str(exc))
        raise SftpConnectionError(
            f"SFTP connection failed for {config.host}:{config.port}: {exc}"
        ) from exc


async def test_sftp_connection(
    config: SftpConnectionConfig,
) -> tuple[bool, str | None]:
    """Asynchronously tests connectivity and credentials with remote SFTP host."""
    return await asyncio.to_thread(_test_sftp_connection_sync, config)


def _test_sftp_connection_sync(config: SftpConnectionConfig) -> tuple[bool, str | None]:
    client = None
    sftp = None
    try:
        client = create_ssh_client(config, diagnostic=True)
        sftp = client.open_sftp()
        logger.info("sftp_diagnostic_ping_success", host=config.host)
        return True, None
    except Exception as exc:  # noqa: BLE001 - Diagnostic check maps all network/auth errors into result tuple
        logger.warning("sftp_diagnostic_ping_failed", host=config.host, error=str(exc))
        return False, str(exc)
    finally:
        if sftp is not None:
            sftp.close()
        if client is not None:
            client.close()


class SftpSession:
    """Context manager executing high-level SFTP batch file operations."""

    def __init__(self, config: SftpConnectionConfig) -> None:
        self._config = config
        self._client: paramiko.SSHClient | None = None
        self._sftp: paramiko.SFTPClient | None = None

    def __enter__(self) -> SftpSession:
        self._client = create_ssh_client(self._config)
        self._sftp = self._client.open_sftp()
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        if self._sftp is not None:
            self._sftp.close()
            self._sftp = None
        if self._client is not None:
            self._client.close()
            self._client = None

    @property
    def raw_sftp(self) -> paramiko.SFTPClient:
        if self._sftp is None:
            raise SftpOperationError("SFTP session is not open.")
        return self._sftp

    def listdir(self, remote_dir: str = ".") -> list[str]:
        try:
            return self.raw_sftp.listdir(remote_dir)
        except Exception as exc:
            raise SftpOperationError(f"Failed to list directory '{remote_dir}': {exc}") from exc

    def listdir_attr(self, remote_dir: str = ".") -> Sequence[SftpFileMetadata]:
        try:
            raw_attrs = self.raw_sftp.listdir_attr(remote_dir)
            return [
                SftpFileMetadata(
                    filename=attr.filename or "",
                    size_bytes=attr.st_size or 0,
                    modified_at=datetime.fromtimestamp(attr.st_mtime or 0, tz=UTC),
                )
                for attr in raw_attrs
            ]
        except Exception as exc:
            raise SftpOperationError(
                f"Failed to list directory attributes '{remote_dir}': {exc}"
            ) from exc

    def get_file(self, remote_path: str) -> bytes:
        try:
            buf = io.BytesIO()
            self.raw_sftp.getfo(remote_path, buf)
            buf.seek(0)
            return buf.read()
        except Exception as exc:
            raise SftpOperationError(
                f"Failed to download remote file '{remote_path}': {exc}"
            ) from exc

    def put_file(self, remote_path: str, data: bytes | str) -> None:
        try:
            payload = data.encode("utf-8") if isinstance(data, str) else data
            with io.BytesIO(payload) as buf:
                self.raw_sftp.putfo(buf, remote_path)
            logger.info("sftp_file_uploaded", remote_path=remote_path, size_bytes=len(payload))
        except Exception as exc:
            raise SftpOperationError(f"Failed to upload to '{remote_path}': {exc}") from exc

    def delete_file(self, remote_path: str) -> None:
        try:
            self.raw_sftp.remove(remote_path)
            logger.info("sftp_file_deleted", remote_path=remote_path)
        except Exception as exc:
            raise SftpOperationError(
                f"Failed to delete remote file '{remote_path}': {exc}"
            ) from exc
