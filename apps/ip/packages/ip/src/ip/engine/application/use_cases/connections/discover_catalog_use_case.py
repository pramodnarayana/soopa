"""Use case to introspect an external system and discover its schema catalog."""

from __future__ import annotations

from collections.abc import Mapping

import structlog
from security.ports.cipher_port import CipherPort

from ip.engine.application.responses import (
    DiscoveredCatalogDTO,
    StreamFieldDTO,
    StreamSchemaDTO,
)
from ip.engine.application.use_cases.connections.token_manager_service import (
    GetValidCredentialsCommand,
    ResolvedConnectionCredentialsDTO,
    TokenManagerService,
)
from ip.engine.domain.exceptions import (
    ConnectionNotFoundError,
    ConnectorNotFoundError,
    InvalidConnectionConfigError,
    Result,
)
from ip.engine.domain.models.catalog import ConnectionCatalog, StreamField, StreamSchema, SyncMode
from ip.engine.ports.outbound.connector_port import ConnectorMetadataPort
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class DiscoverCatalogUseCase:
    """Introspects source systems, discovers streams/fields, and stores catalog versions inside a Control Plane UoW."""

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
    ) -> Result[ResolvedConnectionCredentialsDTO, DiscoveredCatalogDTO]:
        creds_res = await self._token_manager.get_valid_credentials(
            GetValidCredentialsCommand(
                tenant_id=tenant_id,
                connection_id=connection_id,
            )
        )
        if creds_res.is_err or creds_res.value is None:
            err = creds_res.error or ConnectionNotFoundError.for_id(connection_id)
            return Result.fail(DiscoveredCatalogDTO.from_error(connection_id, err))
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

    async def execute(
        self,
        connection_id: str,
        tenant_id: str,
    ) -> DiscoveredCatalogDTO:
        creds_res = await self._resolve_credentials(connection_id, tenant_id)
        if creds_res.is_err or creds_res.value is None:
            return creds_res.error or DiscoveredCatalogDTO.from_error(
                connection_id, ConnectionNotFoundError.for_id(connection_id)
            )
        resolved = creds_res.value

        async with self._uow:
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
                await self._uow.rollback()
                return DiscoveredCatalogDTO.from_error(connection_id, conn_err)

            catalog_dto = await connector.discover(
                connection_id=resolved.connection_id,
                public_config=resolved.public_config,
                credentials=resolved.credentials,
            )
            if not catalog_dto.success:
                await self._uow.rollback()
                return catalog_dto

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

            active_catalog = await self._uow.catalogs.get_active_by_connection_id(connection_id)
            next_version = (active_catalog.catalog_version + 1) if active_catalog else 1

            catalog_res = ConnectionCatalog.try_create(
                connection_id=resolved.connection_id,
                catalog_version=next_version,
                streams=domain_streams,
            )
            if catalog_res.error is not None or catalog_res.value is None:
                cfg_err = catalog_res.error or InvalidConnectionConfigError(
                    field_name="connection_id",
                    message="Invalid connection_id for catalog creation.",
                )
                await self._uow.rollback()
                return DiscoveredCatalogDTO.from_error(connection_id, cfg_err)

            catalog_entity = catalog_res.value
            await self._uow.catalogs.save(catalog_entity)
            await self._uow.commit()

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
                )
                for ds in domain_streams
            ]

            logger.info(
                "catalog_discovered",
                connection_id=resolved.connection_id,
                catalog_id=catalog_entity.id,
                catalog_version=next_version,
                stream_count=len(domain_streams),
            )

            return DiscoveredCatalogDTO(
                connection_id=catalog_entity.connection_id,
                catalog_version=catalog_entity.catalog_version,
                catalog_hash=catalog_entity.catalog_hash,
                streams=response_streams,
                discovered_at=catalog_entity.discovered_at,
            )
