"""Connector Catalog Registry providing generic registration and resolution of connectors."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ip.adapters.outbound.connectors.declarative_http_connector import DeclarativeHttpConnector
from ip.application.responses import AppSpecDTO, CatalogAppSummaryDTO
from ip.domain.exceptions import ConnectorNotFoundException
from ip.domain.models.connector_spec import DeclarativeManifest
from ip.ports.outbound.catalog_registry_port import CatalogRegistryPort
from ip.ports.outbound.connector_port import ConnectorPort


class ConnectorCatalogRegistry(CatalogRegistryPort):
    """Generic registry of declarative manifests and native/custom connectors."""

    def __init__(self) -> None:
        self._manifests: dict[str, DeclarativeManifest] = {}
        self._connectors: dict[str, ConnectorPort] = {}
        self._summaries: dict[str, CatalogAppSummaryDTO] = {}

    def register_manifest(self, manifest: DeclarativeManifest) -> None:
        """Registers a declarative HTTP manifest in the catalog."""
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
        self._connectors[connector.app_id] = connector
        self._summaries[connector.app_id] = summary

    def unregister(self, app_id: str) -> None:
        """Removes a connector and its manifest/summary from the catalog."""
        self._manifests.pop(app_id, None)
        self._connectors.pop(app_id, None)
        self._summaries.pop(app_id, None)

    def get_connector(self, app_id: str) -> ConnectorPort:
        """Retrieves a connector instance for the given app_id."""
        if app_id in self._connectors:
            return self._connectors[app_id]
        if app_id in self._manifests:
            return DeclarativeHttpConnector(self._manifests[app_id])
        raise ConnectorNotFoundException(f"Unknown connector '{app_id}'")

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

    def get_app_spec(self, app_id: str) -> AppSpecDTO:
        """Returns the configuration property schema and metadata for an app."""
        if app_id in self._manifests:
            schema = self._manifests[app_id].property_schema
            raw_dict = schema.to_dict()
            properties = raw_dict.get("properties", [])
            return AppSpecDTO(
                app_id=schema.app_id,
                display_name=schema.display_name,
                auth_type=schema.auth_type,
                category=schema.category,
                properties=properties if isinstance(properties, list) else [],
                description=schema.description,
            )
        if app_id in self._connectors:
            connector = self._connectors[app_id]
            spec_dict = connector.spec()
            raw_props = spec_dict.get("properties", [])
            props_list: list[dict[str, Any]] = []
            if isinstance(raw_props, list):
                props_list = [p for p in raw_props if isinstance(p, dict)]
            elif isinstance(raw_props, dict):
                props_list = [
                    {"name": k, **(v if isinstance(v, dict) else {})} for k, v in raw_props.items()
                ]
            summary = self._summaries.get(app_id)
            return AppSpecDTO(
                app_id=app_id,
                display_name=summary.display_name if summary else app_id,
                auth_type=summary.auth_type if summary else "UNKNOWN",
                category=summary.category if summary else "MISC",
                properties=props_list,
                description=summary.description if summary else None,
            )
        raise ConnectorNotFoundException(f"Unknown connector '{app_id}'")
