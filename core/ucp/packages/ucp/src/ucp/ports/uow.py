from abc import ABC, abstractmethod
from typing import Any, Self

from ucp.ports.api_token_repository import ApiTokenRepositoryPort
from ucp.ports.outbound.app_repository import IAppRepository
from ucp.ports.outbound.tenant_repository import ITenantRepository
from ucp.ports.outbound.user_repository import IUserRepository


class UcpUnitOfWorkPort(ABC):
    """
    Port for the UCP Unit of Work.
    Encapsulates all database repositories and manages the transactional boundary.
    """

    tenant_repo: ITenantRepository
    user_repo: IUserRepository
    api_token_repo: ApiTokenRepositoryPort
    app_repo: IAppRepository

    @abstractmethod
    async def __aenter__(self) -> Self:
        pass

    @abstractmethod
    async def __aexit__(self, exc_type: any, exc_val: any, exc_tb: any) -> None:
        pass

    @abstractmethod
    async def commit(self) -> None:
        pass

    @abstractmethod
    async def rollback(self) -> None:
        pass

    @abstractmethod
    def register_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        """Register a domain event to be saved in the transactional outbox upon commit."""
