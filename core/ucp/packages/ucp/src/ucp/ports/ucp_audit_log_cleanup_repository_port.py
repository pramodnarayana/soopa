from abc import ABC, abstractmethod


class IUcpAuditLogCleanupRepositoryPort(ABC):
    @abstractmethod
    async def cleanup_system_audit_logs(self, retention_days: int) -> int:
        pass
