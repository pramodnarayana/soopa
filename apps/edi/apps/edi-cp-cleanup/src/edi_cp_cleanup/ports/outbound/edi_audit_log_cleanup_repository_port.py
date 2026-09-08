from abc import ABC, abstractmethod


class EdiAuditLogCleanupRepositoryPort(ABC):
    @abstractmethod
    async def cleanup_audit_logs(self, retention_days: int, concurrency_limit: int = 5) -> None:
        pass
