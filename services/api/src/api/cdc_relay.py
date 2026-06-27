import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

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

    # Columns from the outbox table
    idempotency_key: str
    event_type: str
    payload: dict[str, Any]
    status: str
    tenant_id: int


@router.post("/relay", status_code=202)
async def relay_cdc_event(
    event: DebeziumUnwrappedEvent,
    queue: MessageQueuePort = Depends(get_message_queue),
) -> None:
    """
    Receives HTTP Webhooks from the standalone Debezium Server and manually
    routes them into AWS SQS queues based on the source table and event_type.
    """
    # Only process INSERTS for the outbox
    if event.op != "c":
        return

    if event.table == "outbox":
        if event.event_type not in ("TRANSLATE", "DELIVER"):
            logger.warning(f"[CDC Relay] Unhandled outbox event type: {event.event_type}")
            raise HTTPException(
                status_code=400, detail=f"Unknown outbox event_type: {event.event_type}"
            )

        queue_name = "TranslateQueue" if event.event_type == "TRANSLATE" else "DeliverQueue"

        # Validate that the payload contains a trace_id required by workers
        trace_id = event.payload.get("trace_id")
        if not trace_id:
            logger.error(
                f"[CDC Relay] Outbox event missing trace_id in payload: {event.idempotency_key}"
            )
            raise HTTPException(
                status_code=400,
                detail="Outbox payload missing required trace_id field",
            )

        # We package the original outbox payload and idempotency key for the worker
        message_body = {
            "idempotency_key": event.idempotency_key,
            "event_type": event.event_type,
            "payload": event.payload,
            "tenant_id": event.tenant_id,
        }

        await queue.send(
            queue_name=queue_name,
            payload=message_body,
        )
        logger.info(f"[CDC Relay] Relayed event_type={event.event_type} to {queue_name}")
    else:
        logger.warning(f"[CDC Relay] Received event for unknown table: {event.table}")
        raise HTTPException(status_code=400, detail="Unknown table source")
