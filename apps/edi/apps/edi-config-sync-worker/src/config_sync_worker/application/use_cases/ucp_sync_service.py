from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from config_sync_worker.adapters.acl.registry import UcpEventNames, translate_external_event
from config_sync_worker.ports.outbound.outbox_port import OutboxPort
from config_sync_worker.ports.outbound.tenant_port import TenantPort
from config_sync_worker.ports.outbound.ucp_event_listener_port import UcpEventListenerPort

logger = structlog.get_logger(__name__)


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
            logger.debug(
                "No translation available for external event: {event.eventType}",
                event_eventType=event.eventType,
            )

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
                    logger.debug(
                        "Ignored unhandled UCP event type: {event.eventType}",
                        event_eventType=event.eventType,
                    )
            except Exception:
                logger.exception(
                    "Failed to process UCP event %s (idempotency_key=%s)",
                    event.eventType,
                    event.idempotencyKey,
                )
                raise
