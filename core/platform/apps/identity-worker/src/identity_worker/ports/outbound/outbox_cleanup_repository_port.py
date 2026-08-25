import abc


class OutboxCleanupRepositoryPort(abc.ABC):
    """
    Port for cleaning up old processed outbox events.
    """

    @abc.abstractmethod
    async def cleanup_outbox(self, retention_days: int) -> int:
        pass
