import asyncio
import uuid

import structlog

from ucp.domain.models.outbox_event import OutboxEvent
from ucp.ports.outbound.outbox_publisher_port import OutboxPublisherPort
from ucp.ports.outbound.outbox_repository_port import OutboxRepositoryPort

logger = structlog.get_logger(__name__)


class SweepControlPlaneOutboxUseCase:
    """
    Application UseCase to sweep the UCP Control Plane Outbox.
    It picks up stuck or failed events and publishes them.
    """

    def __init__(
        self,
        repository: OutboxRepositoryPort,
        publisher: OutboxPublisherPort,
        max_concurrent_events: int = 50,
        lock_lease_ms: int = 30000,
    ):
        self.repository = repository
        self.publisher = publisher
        self.max_concurrent_events = max_concurrent_events
        self.lock_lease_ms = lock_lease_ms
        self.worker_id = str(uuid.uuid4())

    async def execute(self) -> None:
        logger.info("sweep_control_plane_outbox_started", worker_id=self.worker_id)

        # 1. Sweep stuck events
        swept = await self.repository.sweep_stuck_events(self.lock_lease_ms)
        if swept > 0:
            logger.info("stuck_events_swept", count=swept, target_status="PENDING")

        # 2. Claim next events using SKIP LOCKED
        events = await self.repository.claim_next_events(
            worker_id=self.worker_id,
            limit=self.max_concurrent_events,
            lock_lease_ms=self.lock_lease_ms,
        )

        if not events:
            return

        logger.debug("sweeper_events_claimed", worker_id=self.worker_id, count=len(events))

        # 3. Execute concurrently
        tasks = [self.process_event(event) for event in events]
        await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("sweep_control_plane_outbox_completed", events_processed=len(events))

    async def process_event(self, event: OutboxEvent) -> None:
        try:
            await self.publisher.publish(event)
        except Exception as e:
            logger.exception(
                "outbox_event_publishing_failed_by_sweeper",
                event_id=event.id,
                event_type=event.event_type,
            )
            try:
                await self.repository.mark_failed(event.id, self.worker_id, str(e))
            except Exception:
                logger.exception(
                    "outbox_event_mark_failed_error",
                    event_id=event.id,
                )
            return

        try:
            await self.repository.mark_completed(event.id, self.worker_id)
            logger.debug(
                "outbox_event_processed_by_sweeper", event_id=event.id, event_type=event.event_type
            )
        except Exception:
            logger.exception(
                "outbox_event_mark_completed_error",
                event_id=event.id,
            )
