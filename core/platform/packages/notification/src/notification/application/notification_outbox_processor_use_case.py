import asyncio
import uuid
from typing import Any

import structlog

from notification.domain.models import Channel
from notification.ports.outbound.notification_delivery_dispatcher_port import DeliveryDispatcherPort
from notification.ports.outbound.notification_outbox_repository_port import (
    NotificationOutboxRepositoryPort,
)

logger = structlog.get_logger(__name__)


class NotificationOutboxProcessorUseCase:
    """
    Application Service responsible for processing pending outbox messages.
    Purely orchestrates between Ports; has no infrastructure knowledge.
    """

    def __init__(
        self,
        repository: NotificationOutboxRepositoryPort,
        dispatcher: DeliveryDispatcherPort,
        worker_id: str | None = None,
        max_batch_size: int = 50,
        lock_lease_ms: int = 30000,
    ):
        self.repository = repository
        self.dispatcher = dispatcher
        self.worker_id = worker_id or f"notif_relay_{uuid.uuid4().hex[:8]}"
        self.max_batch_size = max_batch_size
        self.lock_lease_ms = lock_lease_ms
        self.is_running = True

    def stop(self) -> None:
        """Signals the processor to cleanly stop taking new batches."""
        self.is_running = False

    async def process_pending(self) -> None:
        """Drains the outbox by continuously claiming and processing batches until empty."""
        while self.is_running:
            try:
                messages = await self.repository.claim_next_messages(
                    self.worker_id, self.max_batch_size, self.lock_lease_ms
                )
                if not messages:
                    break

                logger.info(
                    "Notification Processor claimed batch",
                    count=len(messages),
                    worker_id=self.worker_id,
                )

                tasks = [self._process_message(msg) for msg in messages]
                await asyncio.gather(*tasks, return_exceptions=True)
            except Exception:
                logger.exception("Error draining notification outbox queue")
                break

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
            logger.exception("Failed to process outbox message", message_id=message.id)
            await self.repository.mark_failed(message.id, self.worker_id, str(e))
