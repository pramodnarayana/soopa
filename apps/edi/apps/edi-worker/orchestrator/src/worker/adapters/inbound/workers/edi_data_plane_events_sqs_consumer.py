from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class EdiDataPlaneEventMessage:
    """Standardized DTO for Data Plane SQS events."""

    tenant_id: str
    trace_id: str
    event_type: str
    payload: dict[str, Any]
    idempotency_key: str | None


class EdiDataPlaneEventsSqsConsumer:
    """
    Strict transport adapter for SQS events.
    Parses SQS JSON into a typed DataPlaneEventMessage, initializes structured
    logging observability, and delegates to a registered callback.
    """

    def __init__(self, callback: Callable[[EdiDataPlaneEventMessage], Any]) -> None:
        self._callback = callback

    async def handle(self, body: dict[str, Any]) -> None:
        """Entry point invoked by the SQS poll loop for each received message."""
        payload = body.get("payload", {})
        trace_id = payload.get("trace_id")
        tenant_id = body.get("tenant_id")
        event_type = body.get("event_type", "UNKNOWN")
        idempotency_key = body.get("idempotency_key")

        if not trace_id or not tenant_id:
            logger.error(
                "data_plane_events_sqs_consumer.missing_required_fields",
                trace_id=trace_id,
                tenant_id=tenant_id,
                event_type=event_type,
            )
            return

        # Explicit observability context binding for the entire downstream execution
        bound_logger = logger.bind(trace_id=trace_id, tenant_id=tenant_id, event_type=event_type)
        bound_logger.debug("data_plane_events_sqs_consumer.message_received")

        event = EdiDataPlaneEventMessage(
            tenant_id=tenant_id,
            trace_id=trace_id,
            event_type=event_type,
            payload=payload,
            idempotency_key=idempotency_key,
        )

        try:
            await self._callback(event)
            bound_logger.info("data_plane_events_sqs_consumer.message_processed")
        except Exception:
            bound_logger.exception("data_plane_events_sqs_consumer.processing_failed")
            raise
