from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog
from pubsub.exceptions import ConsumerTerminalError
from pydantic import BaseModel, Field, ValidationError, model_validator
from seedwork.domain.types import JsonDict

logger = structlog.get_logger(__name__)


class EdiDataPlaneEventValidator(BaseModel):
    """
    Pydantic Message Translator at the bounded context inbound edge.

    Accepts the raw JsonDict emitted by AwsSqsConsumer (a serialized EventEnvelope)
    and performs strict runtime validation before yielding a pure domain DTO.
    This is the Anti-Corruption Layer between the transport and the domain.
    """

    event_type: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    payload: JsonDict
    # trace_id is extracted from within the nested payload dict
    trace_id: str = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod

    # this is the anti-corruption layer boundary where typing is enforced post-validation.
    def extract_trace_id_from_payload(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Extract trace_id from the nested payload if not already at the top level."""
        if "trace_id" not in values or not values.get("trace_id"):
            payload = values.get("payload", {})
            if isinstance(payload, dict):
                values["trace_id"] = payload.get("trace_id", "")
        return values


@dataclass(frozen=True)
class EdiDataPlaneEventMessage:
    """Standardized pure domain DTO for Data Plane SQS events."""

    tenant_id: str
    trace_id: str
    event_type: str
    payload: JsonDict
    idempotency_key: str


class EdiDataPlaneEventDispatcher:
    """
    Inbound Adapter (Message Translator) for EDI Data Plane SQS events.

    Receives a raw JsonDict from the transport layer (AwsSqsConsumer),
    strictly validates and translates it into a pure domain EdiDataPlaneEventMessage,
    and delegates to the registered callback.

    This is the bounded context edge — EventEnvelope schema enforcement happens here,
    not in the generic platform transport layer.
    """

    def __init__(self, callback: Callable[[EdiDataPlaneEventMessage], Any]) -> None:
        self._callback = callback

    async def handle(self, body: JsonDict) -> None:
        """Entry point invoked by the SQS poll loop for each received raw message."""
        bound_logger = logger.bind(payload_keys=list(body.keys()))

        try:
            # Message Translator: raw JsonDict → validated Pydantic model → pure domain DTO
            validator = EdiDataPlaneEventValidator.model_validate(body)

            event = EdiDataPlaneEventMessage(
                tenant_id=validator.tenant_id,
                trace_id=validator.trace_id,
                event_type=validator.event_type,
                payload=validator.payload,
                idempotency_key=validator.idempotency_key,
            )
        except ValidationError as e:
            bound_logger.exception(
                "data_plane_events_sqs_consumer.validation_failed",
                error=str(e),
            )
            raise ConsumerTerminalError(f"Permanently malformed EDI data plane message: {e}") from e

        bound_logger = bound_logger.bind(
            trace_id=event.trace_id,
            tenant_id=event.tenant_id,
            event_type=event.event_type,
        )
        bound_logger.debug("data_plane_events_sqs_consumer.message_received")

        try:
            await self._callback(event)
            bound_logger.info("data_plane_events_sqs_consumer.message_processed")
        except Exception:
            bound_logger.exception("data_plane_events_sqs_consumer.processing_failed")
            raise
