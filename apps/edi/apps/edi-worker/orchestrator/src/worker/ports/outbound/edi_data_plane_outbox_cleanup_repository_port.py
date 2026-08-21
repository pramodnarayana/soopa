from abc import ABC, abstractmethod


class EdiDataPlaneOutboxCleanupRepositoryPort(ABC):
    @abstractmethod
    async def cleanup_data_plane_outbox(
        self, retention_days: int, concurrency_limit: int = 5
    ) -> None:
        pass
