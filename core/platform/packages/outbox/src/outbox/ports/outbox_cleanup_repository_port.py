from abc import ABC, abstractmethod


class OutboxCleanupRepositoryPort(ABC):
    @abstractmethod
    async def cleanup_outbox(self, retention_days: int) -> int:
        pass
