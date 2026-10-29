"""Centralized CloudEvents 1.0 EventEnvelope inbound dispatcher for SQS/SNS consumers."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope, EventProcessingLane

from pubsub.enums import ConsumerAction

logger = structlog.get_logger(__name__)

EnvelopeRouteHandler = Callable[[EventEnvelope], Awaitable[ConsumerAction | None]]


@dataclass(frozen=True, kw_only=True)
class EnvelopeValidationError:
    """First-class validation error value object for malformed EventEnvelope payloads."""

    field_name: str
    message: str


def _unwrap_sns_notification(raw_message: JsonDict) -> Result[JsonDict, EnvelopeValidationError]:
    """Unwraps an AWS SNS Notification wrapper if present, or returns raw_message directly."""
    if raw_message.get("Type") == "Notification" and "Message" in raw_message:
        raw_inner = raw_message.get("Message")
        if not isinstance(raw_inner, str):
            return Result.err(
                EnvelopeValidationError(
                    field_name="Message",
                    message="SNS Notification 'Message' attribute must be a JSON string.",
                )
            )
        try:
            decoded = json.loads(raw_inner)
        except json.JSONDecodeError as exc:
            return Result.err(
                EnvelopeValidationError(
                    field_name="Message",
                    message=f"SNS Notification 'Message' contains invalid JSON: {exc}",
                )
            )
        if not isinstance(decoded, dict):
            return Result.err(
                EnvelopeValidationError(
                    field_name="Message",
                    message="SNS Notification 'Message' must decode to a JSON object.",
                )
            )
        return Result.ok(decoded)
    return Result.ok(raw_message)


def parse_event_envelope(raw_message: JsonDict) -> Result[EventEnvelope, EnvelopeValidationError]:
    """Validates and parses a raw SQS/SNS JsonDict into a global seedwork.events.EventEnvelope."""
    unwrapped_res = _unwrap_sns_notification(raw_message)
    if unwrapped_res.is_err:
        return Result.err(unwrapped_res.unwrap_err())
    data = unwrapped_res.unwrap()

    raw_id = data.get("id")
    if not isinstance(raw_id, str) or not raw_id.strip():
        return Result.err(
            EnvelopeValidationError(
                field_name="id",
                message="EventEnvelope 'id' must be a non-empty string.",
            )
        )

    raw_source = data.get("source")
    if not isinstance(raw_source, str) or not raw_source.strip():
        return Result.err(
            EnvelopeValidationError(
                field_name="source",
                message="EventEnvelope 'source' must be a non-empty string.",
            )
        )

    raw_event_type = data.get("event_type")
    if not isinstance(raw_event_type, str) or not raw_event_type.strip():
        return Result.err(
            EnvelopeValidationError(
                field_name="event_type",
                message="EventEnvelope 'event_type' must be a non-empty string.",
            )
        )

    raw_payload = data.get("payload")
    if not isinstance(raw_payload, dict):
        return Result.err(
            EnvelopeValidationError(
                field_name="payload",
                message="EventEnvelope 'payload' must be a JSON object.",
            )
        )

    raw_tenant_id = data.get("tenant_id")
    tenant_id = str(raw_tenant_id) if isinstance(raw_tenant_id, str) and raw_tenant_id else None

    raw_idempotency_key = data.get("idempotency_key")
    idempotency_key = (
        str(raw_idempotency_key)
        if isinstance(raw_idempotency_key, str) and raw_idempotency_key
        else None
    )

    raw_trace_id = data.get("trace_id")
    trace_id = str(raw_trace_id) if isinstance(raw_trace_id, str) and raw_trace_id else None

    raw_correlation_id = data.get("correlation_id")
    correlation_id = (
        str(raw_correlation_id)
        if isinstance(raw_correlation_id, str) and raw_correlation_id
        else None
    )

    raw_lane = data.get("lane", EventProcessingLane.REALTIME.value)
    try:
        lane = EventProcessingLane(str(raw_lane)) if raw_lane else EventProcessingLane.REALTIME
    except ValueError:
        return Result.err(
            EnvelopeValidationError(
                field_name="lane",
                message=f"Unsupported EventEnvelope queue lane: '{raw_lane}'.",
            )
        )

    return Result.ok(
        EventEnvelope(
            id=raw_id,
            source=raw_source,
            event_type=raw_event_type,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            payload=raw_payload,
            trace_id=trace_id,
            correlation_id=correlation_id,
            lane=lane,
        )
    )


class EventEnvelopeDispatcher:
    """
    Platform-wide inbound dispatcher that validates raw SQS/SNS messages directly into
    `seedwork.events.EventEnvelope` and routes by `envelope.event_type`.

    Follows First-Class Error Handling: known validation or routing errors log structured
    errors and return `ConsumerAction.ACK` without raising exceptions.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, EnvelopeRouteHandler] = {}

    def subscribe(self, event_type: str, handler: EnvelopeRouteHandler) -> None:
        """Registers an async route handler for a canonical event_type."""
        self._handlers[event_type] = handler

    @property
    def registered_event_types(self) -> tuple[str, ...]:
        """Returns the tuple of all subscribed event types."""
        return tuple(self._handlers.keys())

    async def handle(self, raw_message: JsonDict) -> ConsumerAction:
        """Entrypoint callback compatible with SqsConsumerManager.handler."""
        parsed = parse_event_envelope(raw_message)
        if parsed.is_err:
            err = parsed.unwrap_err()
            logger.error(
                "event_envelope_validation_failed",
                field=err.field_name,
                reason=err.message,
            )
            return ConsumerAction.ACK

        envelope = parsed.unwrap()
        return await self.dispatch_envelope(envelope)

    async def dispatch_envelope(self, envelope: EventEnvelope) -> ConsumerAction:
        """Dispatches a validated `EventEnvelope` to its registered route handler."""
        handler = self._handlers.get(envelope.event_type)
        if handler is None:
            logger.error(
                "event_envelope_unregistered_event_type",
                event_id=envelope.id,
                source=envelope.source,
                event_type=envelope.event_type,
                tenant_id=envelope.tenant_id,
                trace_id=envelope.trace_id,
            )
            return ConsumerAction.ACK

        with structlog.contextvars.bound_contextvars(
            event_id=envelope.id,
            source=envelope.source,
            event_type=envelope.event_type,
            tenant_id=envelope.tenant_id,
            trace_id=envelope.trace_id,
            correlation_id=envelope.correlation_id,
            lane=envelope.lane.value,
        ):
            action = await handler(envelope)
            return action or ConsumerAction.ACK

    async def dispatch(self, raw_message: JsonDict) -> ConsumerAction:
        """Alias for `handle(raw_message)` satisfying `SqsConsumerManager.handler`."""
        return await self.handle(raw_message)


__all__ = [
    "EnvelopeRouteHandler",
    "EnvelopeValidationError",
    "EventEnvelopeDispatcher",
    "parse_event_envelope",
]
