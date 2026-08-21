from abc import ABC, abstractmethod


class UcpIdempotencyCleanupRepositoryPort(ABC):
    @abstractmethod
    async def cleanup_idempotency_results(self, retention_days: int) -> int:
        pass
