from abc import ABC, abstractmethod
from typing import Any, Self

from ucp.ports.outbound.api_token_repository_port import ApiTokenRepositoryPort
from ucp.ports.outbound.app_repository_port import AppRepositoryPort
from ucp.ports.outbound.idempotency_repository_port import IdempotencyRepositoryPort
from ucp.ports.outbound.role_repository_port import RoleRepositoryPort
from ucp.ports.outbound.tenant_repository_port import TenantRepositoryPort
from ucp.ports.outbound.user_repository_port import UserRepositoryPort
from ucp.ports.outbound.webhook_repository_port import WebhookRepositoryPort


class UcpUnitOfWorkPort(ABC):
    """
    Port for the UCP Unit of Work.
    Encapsulates all database repositories and manages the transactional boundary.
    """

    tenant_repo: TenantRepositoryPort
    user_repo: UserRepositoryPort
    api_token_repo: ApiTokenRepositoryPort
    app_repo: AppRepositoryPort
    role_repo: RoleRepositoryPort
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
