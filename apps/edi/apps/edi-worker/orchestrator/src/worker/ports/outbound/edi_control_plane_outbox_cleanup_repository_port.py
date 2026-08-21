from abc import ABC, abstractmethod


class EdiControlPlaneOutboxCleanupRepositoryPort(ABC):
    @abstractmethod
    async def cleanup_control_plane_outbox(self, retention_days: int) -> int:
        pass
