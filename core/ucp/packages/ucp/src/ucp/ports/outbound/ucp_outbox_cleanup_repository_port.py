from abc import ABC, abstractmethod


class UcpOutboxCleanupRepositoryPort(ABC):
    @abstractmethod
    async def cleanup_outbox(self, retention_days: int) -> int:
        pass
