import logging
from typing import Any

from domain.events import MessageQueueName
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, ValidationError

from api.dependencies import get_message_queue
from api.ports.message_queue import MessageQueuePort

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/cdc", tags=["CDC Relay"])


class DebeziumUnwrappedEvent(BaseModel):
    """
    Pydantic model representing the unwrapped payload from Debezium HttpSink.
    """

    op: str = Field(alias="__op", description="Operation type: 'c' for create, 'u' for update")
    table: str = Field(alias="__table", description="The source table name")

    # Core Outbox fields
    idempotency_key: str | None = None
    event_type: str | None = None
    payload: dict[str, Any] | str | None = None
    tenant_id: int | None = None

    class Config:
        extra = "ignore"  # Debezium sends many extra metadata fields we don't need


@router.api_route("/relay", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], status_code=200)
async def relay_cdc_event(
    request: Request,
    queue: MessageQueuePort = Depends(get_message_queue),
) -> dict[str, str]:
    """
    Receives HTTP Webhooks from the standalone Debezium Server and manually
    routes them into AWS SQS queues based on the source table and event_type.

    Enterprise Grade Notes:
    - Bypasses default FastAPI strict typing in the method signature to handle Debezium's
      inconsistent Content-Type headers, but strictly validates the JSON via Pydantic internally.
    - Handles both batched (List) and single (Object) payloads.
    - Implements the Robustness Principle (Postel's Law) for internal infrastructure webhooks.
    """
    import json

    body = await request.body()
    try:
        data = json.loads(body)
    except Exception as e:
        logger.error(f"[CDC Relay] CRITICAL: Failed to parse raw CDC bytes as JSON: {e}")
        # In a full enterprise setup, this raw body would be pushed to an S3 Dead Letter bucket here.
        return {"status": "ok"}

    # Normalize to a list
    raw_events = data if isinstance(data, list) else [data]

    # Strictly validate against our schema
    validated_events: list[DebeziumUnwrappedEvent] = []
    for raw_event in raw_events:
        try:
            validated_events.append(DebeziumUnwrappedEvent(**raw_event))
        except (ValidationError, TypeError) as e:
            logger.error(
                f"[CDC Relay] Schema validation failed for event: {e}. Payload: {raw_event}"
            )
            # Skip invalid events; do not fail the entire batch.
            continue

    for event in validated_events:
        if event.op != "c":
            continue

        if event.table == "outbox":
            # Outbox table routing logic
            if not event.event_type:
                logger.warning(
                    f"[CDC Relay] Outbox event missing event_type. Skipping: {event.idempotency_key}"
                )
                continue

            event_payload = event.payload
            if isinstance(event_payload, str):
                try:
                    payload_dict = json.loads(event_payload)
                except json.JSONDecodeError as e:
                    logger.error(
                        f"[CDC Relay] Invalid JSON in outbox payload for key {event.idempotency_key}: {e}"
                    )
                    continue
            else:
                payload_dict = event_payload

            if event.event_type in (
                "TRANSLATE",
                "json.received",
                "edi_message.received",
                "DELIVER",
            ):
                queue_name = (
                    MessageQueueName.TRANSLATE
                    if event.event_type in ("TRANSLATE", "json.received", "edi_message.received")
                    else MessageQueueName.DELIVER
                )

                # Validate that the payload contains a trace_id required by data plane workers
                trace_id = payload_dict.get("trace_id") if isinstance(payload_dict, dict) else None
                if not trace_id:
                    logger.error(
                        f"[CDC Relay] Outbox event missing trace_id in payload: {event.idempotency_key}"
                    )
                    continue
            else:
                queue_name = MessageQueueName.PROVISIONING

            message_body = {
                "idempotency_key": event.idempotency_key,
                "event_type": event.event_type,
                "payload": payload_dict,
                "tenant_id": event.tenant_id,
            }

            await queue.send(queue_name=queue_name, payload=message_body)
            logger.info(f"[CDC Relay] Relayed event_type={event.event_type} to {queue_name}")
        else:
            logger.debug(f"[CDC Relay] Ignoring event for unhandled table: {event.table}")
    return {"status": "ok"}
