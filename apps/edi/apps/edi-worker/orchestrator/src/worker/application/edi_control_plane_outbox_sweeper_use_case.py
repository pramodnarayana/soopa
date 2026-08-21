import structlog

from worker.ports.outbound.outbox_relay_repository_port import OutboxRelayRepositoryPort

logger = structlog.get_logger(__name__)


class EdiControlPlaneOutboxSweeperUseCase:
    def __init__(self, repository: OutboxRelayRepositoryPort) -> None:
        self.repository = repository

    async def execute(self) -> None:
        """
        Sweeps the Control Plane Outbox for abandoned PENDING events
        that might have been missed by the real-time Postgres NOTIFY listener.
        It relies on the OutboxRelay to actually publish the events.
        """
        logger.info("control_plane_outbox_sweep_started")
        try:
            count = await self.repository.sweep_stuck_events(lock_lease_ms=30000)

            if count > 0:
                logger.info(
                    "swept_abandoned_pending_events",
                    count=count,
                    target="edi.outbox",
                )
            else:
                logger.debug("no_stuck_events_found")
        except Exception:
            logger.exception("control_plane_outbox_sweep_failed")
            raise
