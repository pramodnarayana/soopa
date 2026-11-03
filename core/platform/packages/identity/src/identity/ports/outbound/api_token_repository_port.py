from abc import ABC, abstractmethod

from identity.domain.api_token import ApiToken


class ApiTokenRepositoryPort(ABC):
    """Port for managing API Token persistence operations."""

    @abstractmethod
    async def get_all_by_tenant(self, tenant_id: str) -> list[ApiToken]:
        pass

    @abstractmethod
    async def get_by_id(self, token_id: str, tenant_id: str) -> ApiToken | None:
        pass

    @abstractmethod
    async def save(self, token: ApiToken) -> ApiToken:
        pass

    @abstractmethod
    async def delete(self, token_id: str, tenant_id: str) -> bool:
        pass

    @abstractmethod
    async def get_by_client_id(self, client_id: str) -> ApiToken | None:
        pass
