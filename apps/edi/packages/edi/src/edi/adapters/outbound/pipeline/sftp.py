"""SFTP Outbound Delivery Adapter delegating to centralized platform sftp package."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog
from sftp import (
    SftpAuthenticationError,
    SftpConnectionConfig,
    SftpConnectionError,
    SftpHostValidationError,
    SftpOperationError,
    SftpSession,
    create_ssh_client,
)

from edi.ports.outbound.exceptions import PortAuthenticationError, PortConnectionError
from edi.ports.outbound.sftp_delivery_port import SftpDeliveryPort

if TYPE_CHECKING:
    import paramiko

logger = structlog.get_logger(__name__)


def get_ssh_client(
    host: str,
    port: int,
    username: str,
    password: str | None = None,
    client_key_string: str | None = None,
    host_key_string: str | None = None,
    timeout: int = 10,
    allow_local: bool = True,
) -> paramiko.SSHClient:
    """Creates a configured paramiko SSHClient delegating to centralized sftp package."""
    config = SftpConnectionConfig(
        host=host,
        port=port,
        username=username,
        password=password,
        private_key=client_key_string,
        host_key=host_key_string,
        timeout_seconds=float(timeout),
        allow_local=allow_local,
    )
    return create_ssh_client(config)


class ParamikoSftpClient(SftpDeliveryPort):
    """Concrete implementation of SftpDeliveryPort delegating to centralized platform sftp."""

    async def deliver(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        host_key: str | None,
        client_key: str | None,
        remote_path: str,
        filename: str,
        payload: bytes,
    ) -> None:
        await asyncio.to_thread(
            self._deliver_sync,
            host,
            port,
            username,
            password,
            host_key,
            client_key,
            remote_path,
            filename,
            payload,
        )

    def _deliver_sync(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        host_key: str | None,
        client_key: str | None,
        remote_path: str,
        filename: str,
        payload: bytes,
    ) -> None:
        if not host_key:
            raise ValueError("SFTP host_key is required for server verification")

        config = SftpConnectionConfig(
            host=host,
            port=port,
            username=username,
            password=password or None,
            private_key=client_key or None,
            host_key=host_key,
            allow_local=True,
            timeout_seconds=15.0,
        )

        target_file = f"{remote_path.rstrip('/')}/{filename}" if remote_path else filename

        try:
            with SftpSession(config) as session:
                session.put_file(target_file, payload)
                logger.info(
                    "sftp_delivery_succeeded",
                    filename=filename,
                    host=host,
                    port=port,
                    target_file=target_file,
                )
        except SftpAuthenticationError as exc:
            raise PortAuthenticationError(f"SFTP authentication failed: {exc}") from exc
        except (SftpConnectionError, SftpHostValidationError, SftpOperationError) as exc:
            raise PortConnectionError(f"SFTP delivery failed for {host}:{port}: {exc}") from exc
