from typing import Protocol


class ApiTokenPort(Protocol):
    async def create_api_token(
        self, tenant_id: int, name: str, client_id: str, key_hash: str
    ) -> None:
        """
        Creates an API Token in the global database.
        Must handle idempotency (upsert/ignore if client_id already exists).
        """
        ...
