from abc import ABC, abstractmethod
from typing import Any, Self

from ucp.ports.api_token_repository import ApiTokenRepositoryPort
from ucp.ports.idempotency_repository import IdempotencyRepositoryPort
from ucp.ports.outbound.app_repository import IAppRepository
from ucp.ports.outbound.role_repository import IRoleRepository
from ucp.ports.outbound.tenant_repository import ITenantRepository
from ucp.ports.outbound.user_repository import IUserRepository
from ucp.ports.webhook_repository import WebhookRepositoryPort


class UcpUnitOfWorkPort(ABC):
    """
    Port for the UCP Unit of Work.
    Encapsulates all database repositories and manages the transactional boundary.
    """

    tenant_repo: ITenantRepository
    user_repo: IUserRepository
    api_token_repo: ApiTokenRepositoryPort
    app_repo: IAppRepository
    role_repo: IRoleRepository
    webhook_repo: WebhookRepositoryPort
    idempotency_repo: IdempotencyRepositoryPort

    @abstractmethod
    async def __aenter__(self) -> Self:
        pass

    @abstractmethod
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    @abstractmethod
    async def commit(self) -> None:
        pass

    @abstractmethod
    async def rollback(self) -> None:
        pass
