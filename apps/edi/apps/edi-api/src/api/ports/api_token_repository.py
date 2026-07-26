from typing import Protocol


class ApiTokenRepositoryPort(Protocol):
    """
    Port for managing platform API tokens.
    Implemented by SqlAlchemyApiTokenRepository (adapter).
    Can be stubbed in unit tests with any class that satisfies this interface.
    """

    async def get_tenant_id_by_credentials(
        self, client_id: str, secret_hash: str
    ) -> str | None: ...
