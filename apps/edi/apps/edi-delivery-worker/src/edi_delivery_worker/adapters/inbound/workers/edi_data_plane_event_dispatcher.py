from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog
from edi.domain.exceptions import InvalidMessageError
from pubsub.aws.debezium_parser import DebeziumPayloadParser

logger = structlog.get_logger(__name__)


@dataclass
class EdiDataPlaneEventMessage:
    """Standardized DTO for Data Plane SQS events."""

    tenant_id: str
    trace_id: str
    event_type: str
    payload: dict[str, Any]
    idempotency_key: str

    def __post_init__(self) -> None:
        if not self.tenant_id or not self.tenant_id.strip():
            raise InvalidMessageError("Required field 'tenant_id' is missing or empty")
        if not self.trace_id or not self.trace_id.strip():
            raise InvalidMessageError("Required field 'trace_id' is missing or empty")
        if not self.event_type or not self.event_type.strip():
            raise InvalidMessageError("Required field 'event_type' is missing or empty")
        if not self.idempotency_key or not self.idempotency_key.strip():
            raise InvalidMessageError("Required field 'idempotency_key' is missing or empty")
        if not isinstance(self.payload, dict):
            raise InvalidMessageError("Required field 'payload' must be a valid dictionary")


class EdiDataPlaneEventDispatcher:
    """
    Strict transport adapter for SQS events.
    Parses SQS JSON into a typed DataPlaneEventMessage, initializes structured
    logging observability, and delegates to a registered callback.
    """

    def __init__(self, callback: Callable[[EdiDataPlaneEventMessage], Any]) -> None:
        self._callback = callback

    async def handle(self, body: dict[str, Any]) -> None:
        """Entry point invoked by the SQS poll loop for each received message."""
        payload = DebeziumPayloadParser.extract_payload(body)

        try:
            tenant_id = body.get("tenant_id")
            trace_id = payload.get("trace_id") if isinstance(payload, dict) else None
            event_type = body.get("event_type")
            idempotency_key = body.get("idempotency_key")

            if not tenant_id or not str(tenant_id).strip():
                raise InvalidMessageError("Required field 'tenant_id' is missing or empty")
            if not trace_id or not str(trace_id).strip():
                raise InvalidMessageError("Required field 'trace_id' is missing or empty")
            if not event_type or not str(event_type).strip():
                raise InvalidMessageError("Required field 'event_type' is missing or empty")
            if not idempotency_key or not str(idempotency_key).strip():
                raise InvalidMessageError("Required field 'idempotency_key' is missing or empty")

            event = EdiDataPlaneEventMessage(
                tenant_id=str(tenant_id),
                trace_id=str(trace_id),
                event_type=str(event_type),
                payload=payload if payload is not None else {},
                idempotency_key=str(idempotency_key),
            )
        except InvalidMessageError as e:
            logger.exception(
                "data_plane_events_sqs_consumer.validation_failed",
                error=str(e),
                event_type=body.get("event_type"),
                tenant_id=body.get("tenant_id"),
            )
            return

        # Explicit observability context binding for the entire downstream execution
        bound_logger = logger.bind(
            trace_id=event.trace_id, tenant_id=event.tenant_id, event_type=event.event_type
        )
        bound_logger.debug("data_plane_events_sqs_consumer.message_received")

        try:
            await self._callback(event)
            bound_logger.info("data_plane_events_sqs_consumer.message_processed")
        except Exception:
            bound_logger.exception("data_plane_events_sqs_consumer.processing_failed")
            raise
