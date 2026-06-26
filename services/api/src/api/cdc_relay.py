import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/cdc", tags=["CDC Relay"])


class DebeziumUnwrappedEvent(BaseModel):
    """
    Pydantic model representing the unwrapped payload from Debezium HttpSink.
    """

    op: str = Field(alias="__op", description="Operation type: 'c' for create, 'u' for update")
    table: str = Field(alias="__table", description="The source table name")
    trace_id: str
    s3_uri: str


# In a real environment, this would be injected via a dependency
# For the stub, we just simulate an SQS client
class SQSQueueService:
    async def send(self, queue_name: str, payload: dict[str, object]) -> None:
        logger.info(f"Relaying event to SQS queue '{queue_name}': {payload}")


queue_service = SQSQueueService()


@router.post("/relay", status_code=202)
async def relay_cdc_event(event: DebeziumUnwrappedEvent) -> None:
    """
    Receives HTTP Webhooks from the standalone Debezium Server and manually
    routes them into AWS SQS queues based on the source table.
    """
    # Only process INSERTS, ignoring updates/deletes for the append-only outbox
    if event.op != "c":
        return

    # Route specifically for the EDI transformer
    if event.table == "edi_transformer_outbox":
        await queue_service.send(
            queue_name="EdiTransformerQueue",
            payload={"trace_id": event.trace_id, "s3_uri": event.s3_uri},
        )
        logger.info(f"[CDC Relay] Relayed event for trace={event.trace_id} to EdiTransformerQueue")
    else:
        logger.warning(f"[CDC Relay] Received event for unknown table: {event.table}")
        raise HTTPException(status_code=400, detail="Unknown table source")
