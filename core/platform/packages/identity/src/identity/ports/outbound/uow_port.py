from types import TracebackType
from typing import Protocol, Self

from identity.ports.outbound.api_token_repository_port import ApiTokenRepositoryPort
from identity.ports.outbound.role_repository_port import RoleRepositoryPort
from identity.ports.outbound.user_repository_port import UserRepositoryPort


class IdentityUnitOfWorkPort(Protocol):
    """
    Port defining the Unit of Work for the Identity bounded context.
    Encapsulates transaction boundaries and provides access to identity repositories.
    """

    user_repo: UserRepositoryPort
    role_repo: RoleRepositoryPort
    api_token_repo: ApiTokenRepositoryPort

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
