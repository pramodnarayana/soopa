import structlog

from identity_worker.ports.outbound.outbox_repository_port import OutboxRepositoryPort

logger = structlog.get_logger(__name__)


class IdentityOutboxSweeperJob:
    """
    Background job that sweeps stuck outbox events back to PENDING.
    Events can become stuck in PROCESSING if the worker crashes before marking them COMPLETED.
    """

    def __init__(
        self, repository: OutboxRepositoryPort, lock_lease_ms: int = 30000
    ):
        self.repository = repository
        self.lock_lease_ms = lock_lease_ms

    async def run(self) -> None:
        try:
            logger.debug("identity_outbox_sweeper.started")
            swept = await self.repository.sweep_stuck_events(self.lock_lease_ms)
            logger.debug("identity_outbox_sweeper.completed", swept_count=swept)
        except Exception:
            logger.exception("identity_outbox_sweeper.failed")
