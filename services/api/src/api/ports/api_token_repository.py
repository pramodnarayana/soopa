from typing import Any, Protocol
from uuid import UUID


class ApiTokenRepositoryPort(Protocol):
    """
    Port for managing platform API tokens.
    Implemented by SqlAlchemyApiTokenRepository (adapter).
    Can be stubbed in unit tests with any class that satisfies this interface.
    """

    async def create_api_token(
        self,
        tenant_id: int,
        name: str,
        client_id: str,
        secret_hash: str,
        expires_at: Any | None,
    ) -> UUID: ...

    async def list_api_tokens(self, tenant_id: int) -> list[dict[str, Any]]: ...

    async def update_api_token(
        self, tenant_id: int, token_id: UUID, name: str | None = None, active: bool | None = None
    ) -> bool: ...

    async def delete_api_token(self, tenant_id: int, token_id: UUID) -> bool: ...

    async def get_tenant_id_by_credentials(
        self, client_id: str, secret_hash: str
    ) -> int | None: ...
