from abc import ABC, abstractmethod


class IUcpIdempotencyCleanupRepositoryPort(ABC):
    @abstractmethod
    async def cleanup_idempotency_results(self, retention_days: int) -> int:
        pass
