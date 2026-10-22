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
from ip.engine.domain.enums import ConnectionStatus
from ip.engine.domain.exceptions import (
    ConnectionDeactivatedError,
    ConnectionNotFoundError,
    ConnectorNotFoundError,
    InvalidConnectionConfigError,
)
from ip.engine.domain.models.catalog import ConnectionCatalog, StreamField, StreamSchema, SyncMode
from ip.engine.ports.outbound.connector_port import ConnectorMetadataPort
from ip.engine.ports.outbound.uow import ControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class DiscoverCatalogUseCase:
    """Introspects source systems, discovers streams/fields, and stores catalog versions inside a Control Plane UoW."""

    def __init__(
        self,
        uow: ControlPlaneUnitOfWorkPort,
        cipher: CipherPort,
        connectors: Mapping[str, ConnectorMetadataPort],
    ) -> None:
        self._uow = uow
        self._cipher = cipher
        self._connectors = connectors

    async def execute(
        self,
        connection_id: str,
        tenant_id: str | None = None,
    ) -> DiscoveredCatalogDTO:
        async with self._uow:
            connection = await self._uow.connections.get_by_id(connection_id)
            if not connection or (tenant_id is not None and connection.tenant_id != tenant_id):
                not_found_err = ConnectionNotFoundError.for_id(connection_id)
                logger.error(
                    "catalog_discovery_connection_not_found",
                    connection_id=connection_id,
                    error_code=not_found_err.code.value,
                )
                await self._uow.rollback()
                return DiscoveredCatalogDTO.from_error(connection_id, not_found_err)

            if connection.status == ConnectionStatus.DEACTIVATED:
                deact_err = ConnectionDeactivatedError.for_id(connection_id)
                logger.error(
                    "catalog_discovery_connection_deactivated",
                    connection_id=connection_id,
                    error_code=deact_err.code.value,
                )
                await self._uow.rollback()
                return DiscoveredCatalogDTO.from_error(connection_id, deact_err)

            connector = self._connectors.get(connection.app_id)
            if not connector:
                conn_err = ConnectorNotFoundError(
                    app_id=connection.app_id,
                    message=f"Connector '{connection.app_id}' is not registered.",
                    details={"app_id": connection.app_id},
                )
                logger.error(
                    "catalog_discovery_connector_not_found",
                    connection_id=connection_id,
                    app_id=connection.app_id,
                    error_code=conn_err.code.value,
                )
                await self._uow.rollback()
                return DiscoveredCatalogDTO.from_error(connection_id, conn_err)

            credentials = (
                self._cipher.decrypt(connection.encrypted_credentials)
                if connection.encrypted_credentials
                else {}
            )

            catalog_dto = await connector.discover(
                connection_id=connection.id,
                public_config=connection.public_config,
                credentials=credentials,
            )
            if not catalog_dto.success:
                await self._uow.rollback()
                return catalog_dto

            domain_streams: list[StreamSchema] = []
            for s in catalog_dto.streams:
                parsed_sync_modes: list[SyncMode] = []
                for m in s.supported_sync_modes:
                    try:
                        parsed_sync_modes.append(SyncMode(m))
                    except ValueError:
                        logger.info(
                            "unsupported_sync_mode_skipped",
                            stream_name=s.name,
                            mode=m,
                            connection_id=connection_id,
                        )
                if not parsed_sync_modes:
                    logger.info(
                        "stream_skipped_no_supported_sync_modes",
                        stream_name=s.name,
                        connection_id=connection_id,
                    )
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
                connection_id=connection.id,
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
                connection_id=connection.id,
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
