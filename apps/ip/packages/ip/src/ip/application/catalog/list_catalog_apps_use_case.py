"""Use case for listing supported applications in the Integration Platform catalog."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ip.application.responses import CatalogAppSummaryDTO
from ip.ports.outbound.catalog_registry_port import CatalogRegistryPort


@dataclass(frozen=True)
class ListCatalogAppsQuery:
    """Query parameters to filter connector catalog applications."""

    category: str | None = None
    search: str | None = None


class ListCatalogAppsUseCase:
    """Use case coordinating catalog discovery across pre-built and custom connectors."""

    def __init__(self, registry: CatalogRegistryPort) -> None:
        self._registry = registry

    async def execute(self, query: ListCatalogAppsQuery) -> Sequence[CatalogAppSummaryDTO]:
        return self._registry.list_apps(
            category=query.category,
            search=query.search,
        )
