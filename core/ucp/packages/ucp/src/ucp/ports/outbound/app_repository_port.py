from typing import Protocol

from ucp.domain.models.app import App


class AppRepositoryPort(Protocol):
    """
    Outbound port for retrieving App metadata (e.g., from ucp.apps).
    """

    async def find_all(self) -> list[App]:
        """Retrieves all registered platform applications."""
        ...

    async def find_by_id(self, app_id: str) -> App | None:
        """Finds a platform application by ID"""
        ...
