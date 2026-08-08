from typing import Protocol

from ucp.domain.models.app import App


class IAppRepository(Protocol):
    """
    Outbound port for retrieving App metadata (e.g., from ucp.apps).
    """

    async def find_all(self) -> list[App]:
        """Retrieves all registered platform applications."""
        ...
