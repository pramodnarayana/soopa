import logging
from collections.abc import Awaitable, Callable
from typing import Any

from worker.adapters.acl.registry import UcpEventNames, translate_external_event
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
        self._handlers: dict[str, Callable[[Any], Awaitable[None]]] = {
            UcpEventNames.TENANT_PROVISIONED: self._handle_external_event,
            "api_key.created": self._handle_external_event,
        }

    async def _handle_external_event(self, event: Any) -> None:
        translated = translate_external_event(event.eventType, event.payload)
        if translated:
            await self.sync_outbox_port.publish_event(
                event_type=translated["event_type"],
                payload=translated["payload"],
                idempotency_key=event.idempotencyKey,
                tenant_id=event.tenantId,
            )
        else:
            logger.debug(f"No translation available for external event: {event.eventType}")

    async def process_messages(self) -> None:
        """
        Polls the UCP event listener port and processes incoming Identity events.
        """
        async with self.listener_port.process_next_event() as event:
            if not event:
                return

            try:
                handler = self._handlers.get(event.eventType)
                if handler:
                    await handler(event)
                else:
                    logger.debug(f"Ignored unhandled UCP event type: {event.eventType}")
            except Exception as e:
                logger.error(
                    f"Failed to process UCP event {event.eventType} "
                    f"(idempotency_key={event.idempotencyKey}): {e}"
                )
                raise
