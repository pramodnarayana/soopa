"""Native SFTP Connector for batch file operations in the Integration Platform."""

from __future__ import annotations

import io
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any

import paramiko
import structlog
from ip.adapters.outbound.connectors.base_connector import BaseConnector
from ip.application.responses import CatalogAppSummaryDTO
from ip.domain.models.connector_spec import (
    ConnectorProperty,
    ConnectorPropertySchema,
    PropertyType,
)
from ip.domain.types import JsonDict
from ip.ports.types import (
    ConnectionCheckResultDTO,
    DiscoveredCatalogDTO,
    RecordEnvelopeDTO,
    StreamFieldDTO,
    StreamSchemaDTO,
    WriteRecordCommand,
    WriteResultDTO,
)

logger = structlog.get_logger(__name__)


class SftpConnector(BaseConnector):
    """Native Protocol Connector for secure file transfer operations over SFTP using Paramiko."""

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

    def __init__(self, timeout_seconds: float = 15.0) -> None:
        self._timeout_seconds = timeout_seconds

    @property
    def app_id(self) -> str:
        return "sftp"

    def spec(self) -> JsonDict:
        schema = ConnectorPropertySchema(
            app_id="sftp",
            display_name="SFTP File Gateway",
            auth_type="BASIC",
            category="STORAGE",
            description="Secure File Transfer Protocol connector for batch file ingress and delivery",
            properties=(
                ConnectorProperty(
                    name="host",
                    label="SFTP Hostname",
                    type=PropertyType.SHORT_TEXT,
                    required=True,
                    description="Domain or IP address of the remote SFTP server",
                ),
                ConnectorProperty(
                    name="port",
                    label="Port",
                    type=PropertyType.NUMBER,
                    required=True,
                    default=22,
                    description="SSH / SFTP port (default 22)",
                ),
                ConnectorProperty(
                    name="username",
                    label="Username",
                    type=PropertyType.SHORT_TEXT,
                    required=True,
                    description="Authentication username",
                ),
                ConnectorProperty(
                    name="password",
                    label="Password",
                    type=PropertyType.SECRET_TEXT,
                    required=False,
                    description="Password for password-based authentication",
                ),
                ConnectorProperty(
                    name="private_key",
                    label="Private Key (PEM)",
                    type=PropertyType.SECRET_TEXT,
                    required=False,
                    description="RSA / ED25519 Private Key for key-based authentication",
                ),
                ConnectorProperty(
                    name="base_directory",
                    label="Base Directory",
                    type=PropertyType.SHORT_TEXT,
                    required=False,
                    default="/",
                    description="Root remote directory path to monitor",
                ),
            ),
        )
        return schema.to_dict()

    def _create_client(
        self,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # noqa: S507 - Pluggable customer SFTP endpoints require dynamic host verification

        host = str(public_config.get("host", ""))
        port = int(public_config.get("port", 22))
        username = str(credentials.get("username", "") or public_config.get("username", ""))
        password = str(credentials.get("password", "")) if "password" in credentials else None
        private_key_str = (
            str(credentials.get("private_key", "")) if "private_key" in credentials else None
        )

        connect_kwargs: dict[str, Any] = {
            "hostname": host,
            "port": port,
            "username": username,
            "timeout": self._timeout_seconds,
            "look_for_keys": False,
            "allow_agent": False,
        }

        if private_key_str:
            key_file = io.StringIO(private_key_str)
            try:
                connect_kwargs["pkey"] = paramiko.RSAKey.from_private_key(key_file)
            except (paramiko.SSHException, ValueError):
                key_file.seek(0)
                connect_kwargs["pkey"] = paramiko.Ed25519Key.from_private_key(key_file)
        elif password:
            connect_kwargs["password"] = password

        client.connect(**connect_kwargs)
        return client

    async def check(
        self,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> ConnectionCheckResultDTO:
        try:
            client = self._create_client(public_config, credentials)
            client.close()
            return ConnectionCheckResultDTO(
                success=True,
                status="SUCCEEDED",
                message="SFTP connection verified successfully",
            )
        except (paramiko.SSHException, OSError, TimeoutError) as exc:
            logger.warning("sftp_check_failed", error=str(exc))
            return ConnectionCheckResultDTO(
                success=False,
                status="FAILED",
                message=f"Failed to connect to SFTP: {exc}",
                error_code="SFTP_CONNECTION_FAILED",
            )

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
                    StreamFieldDTO(name="content", data_type="string", nullable=True),
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
        client = self._create_client(public_config, credentials)
        try:
            sftp = client.open_sftp()
            try:
                base_dir = str(public_config.get("base_directory", "/"))
                files = sftp.listdir_attr(base_dir)
                for count, f in enumerate(files):
                    if count >= limit:
                        break
                    filename = f.filename
                    data = {
                        "filename": filename,
                        "size_bytes": f.st_size or 0,
                        "modified_at": datetime.fromtimestamp(f.st_mtime or 0, UTC).isoformat(),
                    }
                    yield RecordEnvelopeDTO(
                        stream_name=stream_name,
                        record_id=filename,
                        data=data,
                        emitted_at=datetime.now(UTC).isoformat(),
                    )
            finally:
                sftp.close()
        finally:
            client.close()

    async def write_record(
        self,
        stream_name: str,
        command: WriteRecordCommand,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> WriteResultDTO:
        client = self._create_client(public_config, credentials)
        try:
            sftp = client.open_sftp()
            try:
                filename = command.record_id or str(command.payload.get("filename", "upload.dat"))
                content = str(command.payload.get("content", ""))
                base_dir = str(public_config.get("base_directory", "/")).rstrip("/")
                target_path = f"{base_dir}/{filename}"
                with sftp.file(target_path, "w") as remote_file:
                    remote_file.write(content)

                return WriteResultDTO(
                    success=True,
                    record_id=filename,
                    destination_id=target_path,
                )
            finally:
                sftp.close()
        finally:
            client.close()
