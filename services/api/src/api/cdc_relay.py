import json
import logging
import os

import aioboto3  # type: ignore[import-untyped]
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
class SQSQueueService:
    def __init__(self, endpoint_url: str | None = None, region: str = "us-east-1"):
        self.endpoint_url = endpoint_url
        self.region = region
        self.session = aioboto3.Session()

    async def send(self, queue_name: str, payload: dict[str, object]) -> None:
        trace_id = payload.get("trace_id", "unknown")
        logger.info(f"Relaying event to SQS queue '{queue_name}' for trace_id={trace_id}")

        client_kwargs = {"region_name": self.region}
        if self.endpoint_url:
            client_kwargs["endpoint_url"] = self.endpoint_url

        async with self.session.client("sqs", **client_kwargs) as sqs:
            # Get queue URL from queue name
            queue_url_response = await sqs.get_queue_url(QueueName=queue_name)
            queue_url = queue_url_response["QueueUrl"]

            # Send message to SQS
            await sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(payload))

            logger.info(f"Successfully sent message to SQS queue {queue_name}")


# Initialize with LocalStack endpoint only if AWS_ENDPOINT_URL is explicitly set
endpoint_url = os.getenv("AWS_ENDPOINT_URL")
queue_service = SQSQueueService(endpoint_url=endpoint_url)


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
