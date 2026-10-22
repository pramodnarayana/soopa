"""Connector Catalog Registry providing generic registration and resolution of connectors."""

from __future__ import annotations

from collections.abc import Sequence

from ip.engine.adapters.outbound.connectors.declarative_http_connector import (
    DeclarativeHttpConnector,
)
from ip.engine.adapters.outbound.connectors.spec_mapper import schema_to_app_spec_dto
from ip.engine.application.responses import AppSpecDTO, CatalogAppSummaryDTO
from ip.engine.domain.exceptions import ConnectorNotFoundError, Result
from ip.engine.domain.models.connector_spec import DeclarativeManifest
from ip.engine.ports.outbound.catalog_registry_port import CatalogRegistryPort
from ip.engine.ports.outbound.connector_port import ConnectorPort


class ConnectorCatalogRegistry(CatalogRegistryPort):
    """Generic registry of declarative manifests and native/custom connectors."""

    def __init__(self, allow_private_ips: bool = False) -> None:
        self._allow_private_ips = allow_private_ips
        self._manifests: dict[str, DeclarativeManifest] = {}
        self._connectors: dict[str, ConnectorPort] = {}
        self._cached_declarative_connectors: dict[str, DeclarativeHttpConnector] = {}
        self._summaries: dict[str, CatalogAppSummaryDTO] = {}

    def register_manifest(self, manifest: DeclarativeManifest) -> None:
        """Registers a declarative HTTP manifest in the catalog."""
        self._connectors.pop(manifest.app_id, None)
        self._cached_declarative_connectors.pop(manifest.app_id, None)
        self._manifests[manifest.app_id] = manifest
        self._summaries[manifest.app_id] = CatalogAppSummaryDTO(
            app_id=manifest.app_id,
            display_name=manifest.display_name,
            category=manifest.category,
            auth_type=manifest.auth_type,
            description=manifest.property_schema.description,
            connector_type="DECLARATIVE_HTTP",
        )

    def register_connector(
        self,
        connector: ConnectorPort,
        summary: CatalogAppSummaryDTO,
    ) -> None:
        """Registers a native/custom connector instance along with its catalog summary."""
        self._manifests.pop(connector.app_id, None)
        self._cached_declarative_connectors.pop(connector.app_id, None)
        self._connectors[connector.app_id] = connector
        self._summaries[connector.app_id] = summary

    def unregister(self, app_id: str) -> None:
        """Removes a connector and its manifest/summary from the catalog."""
        self._manifests.pop(app_id, None)
        self._connectors.pop(app_id, None)
        self._cached_declarative_connectors.pop(app_id, None)
        self._summaries.pop(app_id, None)

    def get_connector(self, app_id: str) -> Result[ConnectorPort, ConnectorNotFoundError]:
        """Retrieves a connector instance for the given app_id as a first-class Result."""
        if app_id in self._connectors:
            return Result.ok(self._connectors[app_id])
        if app_id in self._manifests:
            if app_id not in self._cached_declarative_connectors:
                self._cached_declarative_connectors[app_id] = DeclarativeHttpConnector(
                    self._manifests[app_id],
                    allow_private_ips=self._allow_private_ips,
                )
            return Result.ok(self._cached_declarative_connectors[app_id])
        return Result.fail(ConnectorNotFoundError.for_app(app_id))

    def list_apps(
        self,
        category: str | None = None,
        search: str | None = None,
    ) -> Sequence[CatalogAppSummaryDTO]:
        """Lists all registered applications with optional category and search filtering."""
        apps = list(self._summaries.values())
        if category:
            apps = [a for a in apps if a.category.upper() == category.upper()]
        if search:
            query = search.lower()
            apps = [a for a in apps if query in a.app_id.lower() or query in a.display_name.lower()]
        return sorted(apps, key=lambda a: a.display_name)

    def get_app_spec(self, app_id: str) -> Result[AppSpecDTO, ConnectorNotFoundError]:
        """Returns the configuration property schema and metadata for an app as a Result."""
        if app_id in self._manifests:
            schema = self._manifests[app_id].property_schema
            return Result.ok(schema_to_app_spec_dto(schema))
        if app_id in self._connectors:
            return Result.ok(self._connectors[app_id].spec())
        return Result.fail(ConnectorNotFoundError.for_app(app_id))
