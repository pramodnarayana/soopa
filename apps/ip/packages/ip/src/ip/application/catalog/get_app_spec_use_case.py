"""Use case for retrieving dynamic UI property schemas for an application."""

from __future__ import annotations

from dataclasses import dataclass

from ip.application.responses import AppSpecDTO
from ip.ports.outbound.catalog_registry_port import CatalogRegistryPort


@dataclass(frozen=True)
class GetAppSpecQuery:
    """Query to fetch the dynamic configuration specification of an application."""

    app_id: str


class GetAppSpecUseCase:
    """Use case retrieving the dynamic UI modal schema for self-service connector setup."""

    def __init__(self, registry: CatalogRegistryPort) -> None:
        self._registry = registry

    async def execute(self, query: GetAppSpecQuery) -> AppSpecDTO:
        return self._registry.get_app_spec(app_id=query.app_id)
