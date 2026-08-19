from abc import ABC, abstractmethod


class IEdiIdempotencyCleanupRepositoryPort(ABC):
    @abstractmethod
    async def cleanup_idempotency_results(
        self, retention_days: int, concurrency_limit: int = 5
    ) -> None:
        pass
