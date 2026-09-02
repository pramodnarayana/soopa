import asyncio
from collections.abc import Callable
from typing import Any

import structlog

from ucp.ports.outbound.ucp_event_consumer_port import UcpEventMessage

logger = structlog.get_logger(__name__)


class UcpEventDispatcher:
    """
    Centralized Inbound Adapter that polls the SQS Event Listener
    and dispatches Domain Events to registered pure business Application Services.
    """

    def __init__(self) -> None:
        # Route mapping: event_type -> list of async handlers
        self._handlers: dict[str, list[Callable[[UcpEventMessage], Any]]] = {}

    def subscribe(self, event_type: str, handler: Callable[[UcpEventMessage], Any]) -> None:
        """Register a handler for a specific domain event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    async def dispatch_raw(self, payload: dict[str, Any]) -> None:
        """Entrypoint called by the SqsConsumerManager."""
        event = UcpEventMessage(
            id=str(payload.get("eventId") or payload.get("id") or ""),
            event_type=str(payload.get("eventType") or payload.get("event_type") or ""),
            tenant_id=str(payload.get("tenantId") or payload.get("tenant_id") or ""),
            payload=payload.get("payload", {}),
        )
        await self._dispatch(event)

    async def _dispatch(self, event: UcpEventMessage) -> None:
        handlers = self._handlers.get(event.event_type, [])
        if not handlers:
            logger.debug("no_handlers_registered_for_event", event_type=event.event_type)
            return

        # Execute all handlers for this event sequentially or concurrently.
        # Running sequentially here to ensure if one fails, the message is not deleted.
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                    await result
            except Exception:
                handler_name = getattr(handler, "__name__", repr(handler))
                logger.exception(
                    "handler_failed_processing_event",
                    event_type=event.event_type,
                    handler_name=handler_name,
                )
                raise  # Propagate to prevent message deletion
