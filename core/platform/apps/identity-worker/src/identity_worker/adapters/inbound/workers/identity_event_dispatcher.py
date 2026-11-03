import inspect
from collections.abc import Awaitable, Callable

import structlog
from seedwork.domain.types import JsonDict

from identity_worker.ports.inbound.identity_event_consumer_port import IdentityEventMessage

logger = structlog.get_logger(__name__)


class IdentityEventDispatcher:
    """
    Centralized Inbound Adapter that polls the SQS Event Listener
    and dispatches Domain Events to registered pure business Application Services.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[IdentityEventMessage], Awaitable[None]]]] = {}

    def subscribe(
        self, event_type: str, handler: Callable[[IdentityEventMessage], Awaitable[None]]
    ) -> None:
        """Register a handler for a specific domain event type."""
        self._handlers.setdefault(event_type, []).append(handler)

    async def dispatch_raw(self, payload: JsonDict) -> None:
        """Entrypoint called by the SqsConsumerManager."""
        logger.info("identity_event_dispatcher_received_raw_payload", payload=payload)
        event_type = str(payload.get("eventType") or payload.get("event_type") or "")
        if not event_type:
            logger.error("identity_event_dispatcher_missing_event_type", payload=payload)
            raise ValueError("Malformed message: missing event type")

        raw_event_payload = payload.get("payload")
        event_payload: JsonDict = raw_event_payload if isinstance(raw_event_payload, dict) else {}
        raw_idem = payload.get("idempotencyKey") or payload.get("idempotency_key")
        raw_tenant = payload.get("tenantId") or payload.get("tenant_id")

        event = IdentityEventMessage(
            id=str(payload.get("eventId") or payload.get("id") or ""),
            source=str(payload.get("source") or ""),
            event_type=event_type,
            payload=event_payload,
            idempotency_key=raw_idem if isinstance(raw_idem, str) else None,
            tenant_id=raw_tenant if isinstance(raw_tenant, str) else None,
        )
        await self._dispatch(event)

    async def _dispatch(self, event: IdentityEventMessage) -> None:
        handlers = self._handlers.get(event.event_type, [])
        if not handlers:
            logger.debug("no_handlers_registered_for_event", event_type=event.event_type)
            return

        for handler in handlers:
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception(
                    "handler_failed_processing_event",
                    event_type=event.event_type,
                    handler_name=repr(handler),
                )
                raise
