"""Port contract for the Integration Platform connector catalog registry."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from typing import Protocol

from ip.engine.domain.exceptions import ConnectorNotFoundError, Result
from ip.engine.domain.models.connector_spec import DeclarativeManifest
from ip.engine.ports.outbound.connector_port import ConnectorPort
from ip.engine.ports.types import AppSpecDTO, CatalogAppSummaryDTO


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
