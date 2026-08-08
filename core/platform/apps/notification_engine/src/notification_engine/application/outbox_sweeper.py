import asyncio
import logging
import uuid
from typing import Any

from ..domain.models import Channel
from ..ports.interfaces import DeliveryDispatcherPort
from ..ports.outbox_repository import NotificationOutboxRepositoryPort

logger = logging.getLogger(__name__)


class NotificationOutboxSweeper:
    def __init__(
        self,
        repository: NotificationOutboxRepositoryPort,
        dispatcher: DeliveryDispatcherPort,
        worker_id: str | None = None,
        poll_interval_seconds: int = 2,
        max_batch_size: int = 50,
        lock_lease_ms: int = 30000,
    ):
        self.repository = repository
        self.dispatcher = dispatcher
        self.worker_id = worker_id or f"notif_sweeper_{uuid.uuid4().hex[:8]}"
        self.poll_interval_seconds = poll_interval_seconds
        self.max_batch_size = max_batch_size
        self.lock_lease_ms = lock_lease_ms
        self.is_running = False

    def start(self) -> asyncio.Task[Any]:
        self.is_running = True
        return asyncio.create_task(self._run_loop())

    def stop(self) -> None:
        self.is_running = False

    async def _run_loop(self) -> None:
        logger.info(f"Starting Notification Outbox Sweeper (id={self.worker_id})")
        while self.is_running:
            try:
                await self.poll()
            except Exception:
                logger.exception("Error in Notification outbox sweeper")
            await asyncio.sleep(self.poll_interval_seconds)
        logger.info("Notification Outbox Sweeper stopped.")

    async def poll(self) -> None:
        # Sweep stuck messages
        swept = await self.repository.sweep_stuck_messages(self.lock_lease_ms)
        if swept > 0:
            logger.info(f"Swept {swept} stuck notification outbox messages.")

        # Claim new messages
        messages = await self.repository.claim_next_messages(
            self.worker_id, self.max_batch_size, self.lock_lease_ms
        )
        if not messages:
            return

        logger.debug(f"Claimed {len(messages)} notification outbox messages.")

        # Process messages concurrently
        tasks = [self._process_message(msg) for msg in messages]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _process_message(self, message: Any) -> None:
        try:
            payload = message.payload
            channel = Channel(payload["channel"])

            # Call the dispatcher directly
            await self.dispatcher.dispatch(
                channel=channel,
                tenant_id=message.tenant_id,
                content=payload["content"],
                subject=payload.get("subject"),
                data=payload.get("data", {}),
            )

            await self.repository.mark_completed(message.id, self.worker_id)
        except Exception as e:
            logger.exception("Failed to process outbox message %s", message.id)
            await self.repository.mark_failed(message.id, self.worker_id, str(e))
