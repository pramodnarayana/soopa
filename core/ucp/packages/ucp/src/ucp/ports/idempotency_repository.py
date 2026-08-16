from abc import ABC, abstractmethod
from typing import Any


class IdempotencyRepositoryPort(ABC):
    @abstractmethod
    async def get_result(
        self, tenant_id: str, idempotency_key: str
    ) -> tuple[bool, dict[str, Any] | None, int | None]:
        """
        Retrieves the result of an idempotent operation.
        Returns a tuple: (is_completed, response_body, response_status_code)
        If the key doesn't exist, it should reserve it (IN_PROGRESS) and return (False, None, None).
        """

    @abstractmethod
    async def save_result(
        self,
        tenant_id: str,
        idempotency_key: str,
        response_body: dict[str, Any],
        response_status_code: int,
    ) -> None:
        """
        Saves the completed result of an idempotent operation.
        """
