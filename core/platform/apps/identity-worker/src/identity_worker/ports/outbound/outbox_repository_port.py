import abc

from platform_orm.events import EventEnvelope


class OutboxRepositoryPort(abc.ABC):
    """
    Port for interacting with the outbox table in the database.
    """

    @abc.abstractmethod
    async def claim_next_events(
        self, worker_id: str, limit: int, lock_lease_ms: int
    ) -> list[EventEnvelope]:
        pass

    @abc.abstractmethod
    async def sweep_stuck_events(self, lock_lease_ms: int) -> int:
        pass

    @abc.abstractmethod
    async def mark_completed(self, event_id: str, worker_id: str) -> None:
        pass

    @abc.abstractmethod
    async def mark_failed(self, event_id: str, worker_id: str, reason: str) -> None:
        pass
