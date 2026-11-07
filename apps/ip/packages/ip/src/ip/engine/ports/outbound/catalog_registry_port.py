"""Port contract for the Integration Platform connector catalog registry."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from ip.engine.domain.connection.enums import ConnectorArchitectureType
from ip.engine.domain.connection.http_spec import DeclarativeManifest
from ip.engine.domain.exceptions import ConnectorNotFoundError, Result
from ip.engine.ports.outbound.connector_port import AppSpecDTO, ConnectorPort


@dataclass(frozen=True)
class CatalogAppSummaryDTO:
    """Summary representation of a connector catalog application."""

    app_id: str
    display_name: str
    category: str
    auth_type: str
    description: str | None = None
    connector_type: str = ConnectorArchitectureType.DECLARATIVE_HTTP
    icon_url: str | None = None


class CatalogRegistryPort(Protocol):
    """Outbound port for discovering and instantiating application connectors."""

    @abstractmethod
    def get_connector(self, app_id: str) -> Result[ConnectorPort, ConnectorNotFoundError]:
        """Retrieves a configured connector instance for the given application ID."""
        ...

    @abstractmethod
    def list_apps(
        self,
        category: str | None = None,
        search: str | None = None,
    ) -> Sequence[CatalogAppSummaryDTO]:
        """Lists available applications in the catalog matching optional filters."""
        ...

    @abstractmethod
    def get_app_spec(self, app_id: str) -> Result[AppSpecDTO, ConnectorNotFoundError]:
        """Retrieves the dynamic UI property schema for the given application ID."""
        ...

    @abstractmethod
    def register_manifest(self, manifest: DeclarativeManifest) -> None:
        """Registers a declarative HTTP manifest into the live catalog."""
        ...

    @abstractmethod
    def register_connector(
        self,
        connector: ConnectorPort,
        summary: CatalogAppSummaryDTO,
    ) -> None:
        """Registers a native or custom Python connector into the live catalog."""
        ...


class CatalogConnectorMapping(Mapping[str, ConnectorPort]):
    """Read-only Mapping[str, ConnectorPort] view backed by CatalogRegistryPort."""

    def __init__(self, registry: CatalogRegistryPort) -> None:
        self._registry = registry

    def __getitem__(self, key: str) -> ConnectorPort:
        result = self._registry.get_connector(key)
        if result.is_ok and result.value is not None:
            return result.value
        raise KeyError(key)

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        result = self._registry.get_connector(key)
        return result.is_ok and result.value is not None

    def __len__(self) -> int:
        return len(self._registry.list_apps())

    def __iter__(self) -> Iterator[str]:
        return (app.app_id for app in self._registry.list_apps())


__all__ = [
    "CatalogAppSummaryDTO",
    "CatalogConnectorMapping",
    "CatalogRegistryPort",
]
