from abc import ABC, abstractmethod
from typing import Any

from platform_orm.models.identity import ApiToken


class ApiTokenRepositoryPort(ABC):
    """Port for managing API Token CRUD operations within the UCP bounded context."""

    @abstractmethod
    async def get_all_by_tenant(self, tenant_id: str) -> list[ApiToken]:
        pass

    @abstractmethod
    async def get_by_id(self, token_id: str, tenant_id: str) -> ApiToken | None:
        pass

    @abstractmethod
    async def create(self, token: ApiToken) -> ApiToken:
        pass

    @abstractmethod
    async def update(self, token_id: str, tenant_id: str, **kwargs: Any) -> ApiToken | None:
        pass

    @abstractmethod
    async def delete(self, token_id: str, tenant_id: str) -> bool:
        pass

    @abstractmethod
    async def get_by_client_id(self, client_id: str) -> ApiToken | None:
        pass
