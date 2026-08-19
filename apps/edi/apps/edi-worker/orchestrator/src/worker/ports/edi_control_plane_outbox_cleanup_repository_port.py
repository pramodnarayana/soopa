from abc import ABC, abstractmethod


class IEdiControlPlaneOutboxCleanupRepositoryPort(ABC):
    @abstractmethod
    async def cleanup_control_plane_outbox(self, retention_days: int) -> int:
        pass
