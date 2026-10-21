"""Use case to introspect an external system and discover its schema catalog."""

from collections.abc import Mapping

import structlog
from ip.application.responses import DiscoveredCatalogDTO
from ip.domain.exceptions import (
    ConnectionNotFoundException,
    ConnectorNotFoundException,
)
from ip.domain.models.catalog import ConnectionCatalog, StreamField, StreamSchema, SyncMode
from ip.ports.outbound.catalog_repository_port import CatalogRepositoryPort
from ip.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.ports.outbound.connector_port import ConnectorPort
from security.ports.cipher_port import CipherPort

logger = structlog.get_logger(__name__)


class DiscoverCatalogUseCase:
    """Introspects source systems, discovers streams/fields, and stores catalog versions."""

    def __init__(
        self,
        connection_repo: ConnectionRepositoryPort,
        catalog_repo: CatalogRepositoryPort,
        cipher: CipherPort,
        connectors: Mapping[str, ConnectorPort],
    ) -> None:
        self._connection_repo = connection_repo
        self._catalog_repo = catalog_repo
        self._cipher = cipher
        self._connectors = connectors

    async def execute(self, connection_id: str) -> DiscoveredCatalogDTO:
        connection = await self._connection_repo.get_by_id(connection_id)
        if not connection:
            logger.error(
                "catalog_discovery_connection_not_found",
                connection_id=connection_id,
            )
            raise ConnectionNotFoundException(connection_id)

        connector = self._connectors.get(connection.app_id)
        if not connector:
            logger.error(
                "catalog_discovery_connector_not_found",
                connection_id=connection_id,
                app_id=connection.app_id,
            )
            raise ConnectorNotFoundException(f"Connector '{connection.app_id}' is not registered.")

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

        domain_streams: list[StreamSchema] = []
        for s in catalog_dto.streams:
            parsed_sync_modes: list[SyncMode] = []
            for m in s.supported_sync_modes:
                try:
                    parsed_sync_modes.append(SyncMode(m))
                except ValueError:
                    logger.warning(
                        "unsupported_sync_mode_skipped",
                        stream_name=s.name,
                        mode=m,
                        connection_id=connection_id,
                    )
            if not parsed_sync_modes:
                parsed_sync_modes = [SyncMode.FULL_REFRESH]

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

        active_catalog = await self._catalog_repo.get_active_by_connection_id(connection_id)
        next_version = (active_catalog.catalog_version + 1) if active_catalog else 1

        catalog_entity = ConnectionCatalog.create(
            connection_id=connection.id,
            catalog_version=next_version,
            streams=domain_streams,
        )

        await self._catalog_repo.save(catalog_entity)

        logger.info(
            "catalog_discovered",
            connection_id=connection.id,
            catalog_id=catalog_entity.id,
            catalog_version=next_version,
            stream_count=len(catalog_dto.streams),
        )

        return DiscoveredCatalogDTO(
            connection_id=catalog_entity.connection_id,
            catalog_version=catalog_entity.catalog_version,
            catalog_hash=catalog_entity.catalog_hash,
            streams=catalog_dto.streams,
            discovered_at=catalog_entity.discovered_at,
        )
