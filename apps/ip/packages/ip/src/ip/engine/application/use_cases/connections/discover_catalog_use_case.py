"""Use case to statelessly introspect an external system and discover its live schema catalog."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol

import structlog
from security.ports.cipher_port import CipherPort

from ip.engine.application.use_cases.connections.token_manager_service import (
    GetValidCredentialsCommand,
    ResolvedConnectionCredentialsDTO,
    TokenManagerService,
)
from ip.engine.domain.connection.enums import AuthType, ConnectionStatus
from ip.engine.domain.connection.stream_schema import (
    StreamField,
    StreamSchema,
    compute_discovered_streams_hash,
)
from ip.engine.domain.exceptions import (
    CatalogDiscoveryError,
    ConnectionNotFoundError,
    ConnectionPendingAuthError,
    ConnectorNotFoundError,
    InvalidConnectionConfigError,
    IpError,
    IpErrorCode,
    Result,
)
from ip.engine.domain.replication.enums import SyncMode
from ip.engine.ports.outbound.connector_port import (
    ConnectorMetadataPort,
    DiscoveredCatalogDTO,
    StreamFieldDTO,
    StreamSchemaDTO,
)
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class DiscoverCatalogExecutorPort(Protocol):
    """Inbound port for stateless catalog discovery."""

    async def execute(
        self,
        connection_id: str,
        tenant_id: str,
    ) -> Result[DiscoveredCatalogDTO, IpError]: ...


class DiscoverCatalogUseCase(DiscoverCatalogExecutorPort):
    """Statelessly introspects source systems on demand and returns live discovered streams and fields."""

    def __init__(
        self,
        uow: IpControlPlaneUnitOfWorkPort,
        cipher: CipherPort,
        connectors: Mapping[str, ConnectorMetadataPort],
        *,
        token_manager: TokenManagerService | None = None,
    ) -> None:
        self._uow = uow
        self._cipher = cipher
        self._connectors = connectors
        self._token_manager = token_manager or TokenManagerService(
            control_plane_uow=uow,
            cipher=cipher,
        )

    async def _resolve_credentials(
        self,
        connection_id: str,
        tenant_id: str,
    ) -> Result[ResolvedConnectionCredentialsDTO, IpError]:
        creds_res = await self._token_manager.get_valid_credentials(
            GetValidCredentialsCommand(
                tenant_id=tenant_id,
                connection_id=connection_id,
            )
        )
        if creds_res.is_err or creds_res.value is None:
            err = creds_res.error or ConnectionNotFoundError.for_id(connection_id)
            return Result.fail(err)
        return Result.ok(creds_res.value)

    @staticmethod
    def _parse_stream_sync_modes(
        stream_dto: StreamSchemaDTO,
        connection_id: str,
    ) -> list[SyncMode]:
        parsed_sync_modes: list[SyncMode] = []
        for m in stream_dto.supported_sync_modes:
            try:
                parsed_sync_modes.append(SyncMode(m))
            except ValueError:
                logger.info(
                    "unsupported_sync_mode_skipped",
                    stream_name=stream_dto.name,
                    mode=m,
                    connection_id=connection_id,
                )
        if not parsed_sync_modes:
            logger.info(
                "stream_skipped_no_supported_sync_modes",
                stream_name=stream_dto.name,
                connection_id=connection_id,
            )
        return parsed_sync_modes

    @staticmethod
    def _parse_error_code(raw_code: str | None) -> IpErrorCode:
        if not raw_code:
            return IpErrorCode.CATALOG_DISCOVERY_FAILED
        try:
            return IpErrorCode(raw_code)
        except ValueError:
            return IpErrorCode.CATALOG_DISCOVERY_FAILED

    async def execute(
        self,
        connection_id: str,
        tenant_id: str,
    ) -> Result[DiscoveredCatalogDTO, IpError]:
        if not connection_id.strip():
            return Result.fail(
                InvalidConnectionConfigError(
                    field_name="connection_id",
                    message="connection_id cannot be empty.",
                )
            )
        if not tenant_id.strip():
            return Result.fail(
                InvalidConnectionConfigError(
                    field_name="tenant_id",
                    message="tenant_id cannot be empty.",
                )
            )

        creds_res = await self._resolve_credentials(connection_id, tenant_id)
        if creds_res.is_err or creds_res.value is None:
            return Result.fail(creds_res.error or ConnectionNotFoundError.for_id(connection_id))
        resolved = creds_res.value

        connector = self._connectors.get(resolved.app_id)
        if not connector:
            conn_err = ConnectorNotFoundError(
                app_id=resolved.app_id,
                message=f"Connector '{resolved.app_id}' is not registered.",
                details={"app_id": resolved.app_id},
            )
            logger.error(
                "catalog_discovery_connector_not_found",
                connection_id=connection_id,
                app_id=resolved.app_id,
                error_code=conn_err.code.value,
            )
            return Result.fail(conn_err)

        if (
            resolved.connection is not None
            and resolved.connection.status == ConnectionStatus.PENDING_AUTH
            and resolved.auth_type == AuthType.API_KEY
            and not resolved.connection.encrypted_credentials
        ):
            pending_err = ConnectionPendingAuthError.for_connection(connection_id)
            logger.error(
                "catalog_discovery_connection_pending_auth",
                connection_id=connection_id,
                error_code=pending_err.code.value,
            )
            return Result.fail(pending_err)

        catalog_dto = await connector.discover(
            connection_id=resolved.connection_id,
            public_config=resolved.public_config,
            credentials=resolved.credentials,
            tenant_id=resolved.tenant_id,
        )
        if not catalog_dto.success:
            err: IpError = catalog_dto.error or CatalogDiscoveryError(
                connection_id=connection_id,
                code=self._parse_error_code(catalog_dto.error_code),
                message=catalog_dto.error_message or "Catalog discovery failed.",
            )
            return Result.fail(err)

        domain_streams: list[StreamSchema] = []
        for s in catalog_dto.streams:
            parsed_sync_modes = self._parse_stream_sync_modes(s, connection_id)
            if not parsed_sync_modes:
                continue

            domain_streams.append(
                StreamSchema(
                    name=s.name,
                    fields=[
                        StreamField(
                            name=f.name,
                            data_type=f.data_type,
                            nullable=f.nullable,
                            description=f.description,
                        )
                        for f in s.fields
                    ],
                    primary_key=list(s.primary_key),
                    cursor_field=s.cursor_field,
                    supported_sync_modes=parsed_sync_modes,
                )
            )

        dto_stream_lookup = {s.name: s for s in catalog_dto.streams}
        response_streams = [
            StreamSchemaDTO(
                name=ds.name,
                fields=[
                    StreamFieldDTO(
                        name=f.name,
                        data_type=f.data_type,
                        nullable=f.nullable,
                        description=f.description,
                    )
                    for f in ds.fields
                ],
                primary_key=list(ds.primary_key),
                cursor_field=ds.cursor_field,
                supported_sync_modes=[m.value for m in ds.supported_sync_modes],
                default_transformation_id=(
                    dto_stream_lookup[ds.name].default_transformation_id
                    if ds.name in dto_stream_lookup
                    else None
                ),
                default_transformation_version=(
                    dto_stream_lookup[ds.name].default_transformation_version
                    if ds.name in dto_stream_lookup
                    else 1
                ),
            )
            for ds in domain_streams
        ]

        catalog_hash = compute_discovered_streams_hash(domain_streams)
        discovered_at = catalog_dto.discovered_at or datetime.now(UTC).isoformat()

        logger.info(
            "catalog_discovered",
            tenant_id=resolved.tenant_id,
            connection_id=resolved.connection_id,
            catalog_hash=catalog_hash,
            stream_count=len(domain_streams),
        )

        return Result.ok(
            DiscoveredCatalogDTO(
                connection_id=resolved.connection_id,
                catalog_hash=catalog_hash,
                streams=response_streams,
                discovered_at=discovered_at,
                success=True,
            )
        )


__all__ = ["DiscoverCatalogExecutorPort", "DiscoverCatalogUseCase"]
