from abc import ABC, abstractmethod


class EdiDataRetentionCleanupRepositoryPort(ABC):
    @abstractmethod
    async def cleanup_processed_events(
        self, retention_days: int, concurrency_limit: int = 5
    ) -> None:
        pass

    @abstractmethod
    async def cleanup_trace_events(self, retention_days: int, concurrency_limit: int = 5) -> None:
        pass
