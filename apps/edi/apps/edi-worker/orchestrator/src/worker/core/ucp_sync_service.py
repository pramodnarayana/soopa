import logging
from collections.abc import Awaitable, Callable
from typing import Any

from worker.ports.outbox import OutboxPort
from worker.ports.tenant import TenantPort
from worker.ports.ucp_event_listener import UcpEventListenerPort

logger = logging.getLogger(__name__)


class UcpSyncWorkerService:
    def __init__(
        self,
        listener_port: UcpEventListenerPort,
        tenant_port: TenantPort,
        sync_outbox_port: OutboxPort,
    ):
        self.listener_port = listener_port
        self.tenant_port = tenant_port
        self.sync_outbox_port = sync_outbox_port

        # Event handler mapping to avoid if/else chains
        self._handlers: dict[str, Callable[[dict[str, Any]], Awaitable[None]]] = {}

    async def process_messages(self) -> None:
        """
        Polls the UCP event listener port and processes incoming Identity events.
        """
        async with self.listener_port.process_next_event() as event:
            if not event:
                return

            try:
                handler = self._handlers.get(event.eventType.value)
                if handler:
                    await handler(event.payload)
                else:
                    logger.debug(f"Ignored unhandled UCP event type: {event.eventType.value}")
            except Exception as e:
                logger.error(
                    f"Failed to process UCP event {event.eventType.value} "
                    f"(idempotency_key={event.idempotencyKey}): {e}"
                )
                raise
