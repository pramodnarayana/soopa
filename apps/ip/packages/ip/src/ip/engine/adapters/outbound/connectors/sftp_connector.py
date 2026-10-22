"""Native SFTP Connector for batch file operations in the Integration Platform."""

from __future__ import annotations

import asyncio
import stat
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

import paramiko
import structlog
from ip.engine.adapters.outbound.connectors.base_connector import BaseConnector
from ip.engine.application.responses import CatalogAppSummaryDTO
from ip.engine.domain.exceptions import (
    EndpointSecurityViolationError,
    PayloadNotFoundError,
    Result,
    SftpConnectionError,
)
from ip.engine.ports.types import (
    AppSpecDTO,
    ConnectionCheckResultDTO,
    ConnectorPropertyDTO,
    DiscoveredCatalogDTO,
    RecordEnvelopeDTO,
    StreamFieldDTO,
    StreamSchemaDTO,
    WriteRecordCommand,
    WriteResultDTO,
)
from seedwork.domain.types import JsonDict
from sftp import (
    DiagnosticHostKeyPolicy,
    SftpConnectionConfig,
    SftpError,
    create_ssh_client,
)

logger = structlog.get_logger(__name__)


class SftpConnector(BaseConnector):
    """Native Protocol Connector for secure file transfer operations over SFTP using centralized platform sftp."""

    @classmethod
    def default_catalog_summary(cls) -> CatalogAppSummaryDTO:
        return CatalogAppSummaryDTO(
            app_id="sftp",
            display_name="SFTP File Gateway",
            category="STORAGE",
            auth_type="BASIC",
            description="Batch file ingress and delivery over secure SFTP protocol",
            connector_type="NATIVE_PROTOCOL",
        )

    def __init__(self, timeout_seconds: float = 15.0, allow_local: bool = False) -> None:
        self._timeout_seconds = timeout_seconds
        self._allow_local = allow_local

    @property
    def app_id(self) -> str:
        return "sftp"

    def _build_config(
        self,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> SftpConnectionConfig:
        raw_port = public_config.get("port", 22)
        port = int(raw_port) if isinstance(raw_port, (int, float, str)) else 22
        return SftpConnectionConfig(
            host=str(public_config.get("host", "")),
            port=port,
            username=str(credentials.get("username", "") or public_config.get("username", "")),
            password=str(credentials.get("password", "")) if "password" in credentials else None,
            private_key=str(credentials.get("private_key", ""))
            if "private_key" in credentials
            else None,
            private_key_passphrase=(
                str(credentials["private_key_passphrase"])
                if "private_key_passphrase" in credentials
                else None
            ),
            base_directory=str(public_config.get("base_directory", "/")),
            timeout_seconds=self._timeout_seconds,
            allow_local=self._allow_local,
            host_key=str(public_config.get("host_key", "")).strip() or None,
            host_key_fingerprint=str(public_config.get("host_key_fingerprint", "")).strip() or None,
        )

    def spec(self) -> AppSpecDTO:
        return AppSpecDTO(
            app_id="sftp",
            display_name="SFTP File Gateway",
            auth_type="BASIC",
            category="STORAGE",
            description="Secure File Transfer Protocol connector for batch file ingress and delivery",
            properties=(
                ConnectorPropertyDTO(
                    name="host",
                    label="SFTP Hostname",
                    type="shortText",
                    required=True,
                    description="Domain or IP address of the remote SFTP server",
                ),
                ConnectorPropertyDTO(
                    name="port",
                    label="Port",
                    type="number",
                    required=True,
                    default=22,
                    description="SSH / SFTP port (default 22)",
                ),
                ConnectorPropertyDTO(
                    name="username",
                    label="Username",
                    type="shortText",
                    required=True,
                    description="Authentication username",
                ),
                ConnectorPropertyDTO(
                    name="password",
                    label="Password",
                    type="secretText",
                    required=False,
                    description="Password for password-based authentication",
                ),
                ConnectorPropertyDTO(
                    name="private_key",
                    label="Private Key (PEM)",
                    type="secretText",
                    required=False,
                    description="RSA / ED25519 Private Key for key-based authentication",
                ),
                ConnectorPropertyDTO(
                    name="base_directory",
                    label="Base Directory",
                    type="shortText",
                    required=False,
                    default="/",
                    description="Root remote directory path to monitor",
                ),
            ),
        )

    def _create_client(
        self,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> Result[paramiko.SSHClient, SftpConnectionError]:
        host = str(public_config.get("host", ""))
        try:
            config = self._build_config(public_config, credentials)
            host_key_policy = (
                DiagnosticHostKeyPolicy()
                if not config.host_key and not config.host_key_fingerprint
                else None
            )
            client = create_ssh_client(
                config,
                host_key_policy=host_key_policy,
            )
            return Result.ok(client)
        except (paramiko.SSHException, SftpError, OSError, ValueError) as exc:
            logger.error("sftp_client_creation_failed", host=host, error=str(exc))
            return Result.fail(
                SftpConnectionError(
                    host=host,
                    message=f"Failed to connect to SFTP: {exc}",
                )
            )

    async def check(
        self,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> ConnectionCheckResultDTO:
        host = str(public_config.get("host", ""))
        client_res = await asyncio.to_thread(self._create_client, public_config, credentials)
        if client_res.error is not None:
            return ConnectionCheckResultDTO.from_error(client_res.error)
        if client_res.value is None:
            return ConnectionCheckResultDTO.from_error(
                SftpConnectionError(host=host, message="Failed to connect to SFTP")
            )
        client = client_res.value
        await asyncio.to_thread(client.close)
        return ConnectionCheckResultDTO.ok("SFTP connection verified successfully")

    async def discover(
        self,
        connection_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> DiscoveredCatalogDTO:
        streams = [
            StreamSchemaDTO(
                name="files",
                fields=[
                    StreamFieldDTO(name="filename", data_type="string", nullable=False),
                    StreamFieldDTO(name="size_bytes", data_type="number", nullable=False),
                    StreamFieldDTO(name="modified_at", data_type="datetime", nullable=False),
                ],
                primary_key=["filename"],
                cursor_field="modified_at",
            ),
        ]
        return self.build_catalog_dto(
            connection_id=connection_id,
            streams=streams,
        )

    async def list_objects(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Sequence[str]:
        ids: list[str] = []
        async for rec in self.read_stream(
            stream_name=stream_name,
            public_config=public_config,
            credentials=credentials,
            cursor=cursor,
            limit=limit,
        ):
            ids.append(rec.record_id)
        return ids

    async def read_stream(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        cursor: str | None = None,
        limit: int = 100,
    ) -> AsyncIterator[RecordEnvelopeDTO]:
        host = str(public_config.get("host", ""))
        client_res = await asyncio.to_thread(self._create_client, public_config, credentials)
        if client_res.error is not None:
            sftp_err = client_res.error
            logger.error(
                "sftp_read_stream_connection_failed",
                host=host,
                stream_name=stream_name,
                error_code=sftp_err.code.value,
                error=sftp_err.message,
            )
            return
        if client_res.value is None:
            return
        client = client_res.value
        try:
            sftp = await asyncio.to_thread(client.open_sftp)
            try:
                base_dir = str(public_config.get("base_directory", "/"))
                raw_entries = await asyncio.to_thread(sftp.listdir_attr, base_dir)
                file_entries = [
                    f for f in raw_entries if f.st_mode is not None and not stat.S_ISDIR(f.st_mode)
                ]
                file_entries.sort(key=lambda f: (f.st_mtime or 0, f.filename or ""))

                cursor_epoch: float | None = None
                if cursor:
                    try:
                        cursor_epoch = datetime.fromisoformat(cursor).timestamp()
                    except (ValueError, TypeError):
                        cursor_epoch = None

                emitted = 0
                for f in file_entries:
                    mtime = float(f.st_mtime or 0)
                    if cursor_epoch is not None and mtime <= cursor_epoch:
                        continue
                    if emitted >= limit:
                        break
                    emitted += 1
                    filename = f.filename or ""
                    data: JsonDict = {
                        "filename": filename,
                        "size_bytes": f.st_size or 0,
                        "modified_at": datetime.fromtimestamp(mtime, UTC).isoformat(),
                    }
                    yield RecordEnvelopeDTO(
                        stream_name=stream_name,
                        record_id=filename,
                        data=data,
                        emitted_at=datetime.now(UTC).isoformat(),
                    )
            finally:
                await asyncio.to_thread(sftp.close)
        finally:
            await asyncio.to_thread(client.close)

    async def write_record(
        self,
        stream_name: str,
        command: WriteRecordCommand,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> WriteResultDTO:
        host = str(public_config.get("host", ""))
        filename = command.record_id or str(command.payload.get("filename", "upload.dat"))
        if not filename or filename in (".", "..") or "/" in filename or "\\" in filename:
            return WriteResultDTO.from_error(
                EndpointSecurityViolationError(
                    endpoint=host,
                    message=f"Path traversal or invalid filename rejected: '{filename}'",
                ),
                record_id=filename or "rejected",
            )

        client_res = await asyncio.to_thread(self._create_client, public_config, credentials)
        if client_res.error is not None:
            return WriteResultDTO.from_error(
                client_res.error,
                record_id=command.record_id or "failed",
            )
        if client_res.value is None:
            return WriteResultDTO.from_error(
                SftpConnectionError(host=host, message="Failed to connect to SFTP"),
                record_id=command.record_id or "failed",
            )
        client = client_res.value
        try:
            sftp = await asyncio.to_thread(client.open_sftp)
            try:
                content = str(command.payload.get("content", ""))
                base_dir = str(public_config.get("base_directory", "/")).rstrip("/")
                target_path = f"{base_dir}/{filename}"

                def _write_sync() -> None:
                    with sftp.file(target_path, "w") as remote_file:
                        remote_file.write(content)

                try:
                    await asyncio.to_thread(_write_sync)
                except (paramiko.SSHException, OSError, ValueError) as exc:
                    return WriteResultDTO.from_error(
                        SftpConnectionError(
                            host=host,
                            message=f"Failed to write file to SFTP: {exc}",
                        ),
                        record_id=filename,
                    )

                return WriteResultDTO(
                    success=True,
                    record_id=filename,
                    destination_id=target_path,
                )
            finally:
                await asyncio.to_thread(sftp.close)
        except (paramiko.SSHException, OSError, ValueError) as exc:
            return WriteResultDTO.from_error(
                SftpConnectionError(
                    host=host,
                    message=f"Failed to open SFTP session: {exc}",
                ),
                record_id=command.record_id or "failed",
            )
        finally:
            await asyncio.to_thread(client.close)


__all__ = [
    "PayloadNotFoundError",
    "SftpConnector",
]
