import asyncio
import json
import typing

import aioboto3
import structlog
from transformer.application.use_cases import ProcessInboundEdiUseCase

logger = structlog.get_logger(__name__)


class SQSComputeWorker:
    """
    Background worker that continuously polls the TransformComputeQueue
    on AWS SQS and routes messages to the pure Python Use Case.
    """

    def __init__(
        self,
        use_case: ProcessInboundEdiUseCase,
        queue_url: str,
        endpoint_url: str | None = None,
    ):
        self.use_case = use_case
        self.queue_url = queue_url
        self.endpoint_url = endpoint_url
        self._running = False
        self.session = aioboto3.Session()

    async def start(self) -> None:
        self._running = True
        logger.info(
            "Starting SQS worker polling against {self.queue_url}", self_queue_url=self.queue_url
        )

        client_kwargs = {"region_name": "us-east-1"}
        if self.endpoint_url:
            client_kwargs["endpoint_url"] = self.endpoint_url

        async with self.session.client("sqs", **client_kwargs) as sqs:
            while self._running:
                try:
                    # Receive messages from SQS
                    response = await sqs.receive_message(
                        QueueUrl=self.queue_url,
                        MaxNumberOfMessages=10,
                        WaitTimeSeconds=20,
                    )

                    messages = response.get("Messages", [])
                    if not messages:
                        continue

                    for message in messages:
                        await self._process_message(message, sqs)

                except Exception:
                    logger.exception("Error in SQS polling loop")

                    await asyncio.sleep(5)

    async def stop(self) -> None:
        logger.info("Stopping SQS worker...")
        self._running = False

    async def _process_message(
        self, sqs_message: dict[str, object], sqs_client: typing.Any
    ) -> None:
        """Parses the SQS payload and invokes the pure Domain logic."""
        try:
            # Parse and validate JSON body
            body = sqs_message.get("Body")
            if not body:
                raise ValueError("Message Body is missing")

            body_json = json.loads(str(body))

            # Extract and validate required fields
            trace_id = body_json.get("trace_id")
            s3_uri = body_json.get("s3_uri")

            if not trace_id or not isinstance(trace_id, str) or not trace_id.strip():
                raise ValueError("Required field 'trace_id' is missing or empty")

            if not s3_uri or not isinstance(s3_uri, str) or not s3_uri.strip():
                raise ValueError("Required field 's3_uri' is missing or empty")

            trace_id = str(trace_id).strip()
            s3_uri = str(s3_uri).strip()

            logger.info("Worker received SQS message for trace {trace_id}", trace_id=trace_id)
            # Execute Hexagonal Use Case
            result = await self.use_case.execute(trace_id=trace_id, s3_uri=s3_uri)
            logger.info(
                "Successfully transformed EDI into {len(result.transactions)} transactions.",
                val_0=len(result.transactions),
            )

            # Delete message from queue on success
            receipt_handle = sqs_message.get("ReceiptHandle")
            if receipt_handle:
                await sqs_client.delete_message(
                    QueueUrl=self.queue_url, ReceiptHandle=str(receipt_handle)
                )
                logger.debug("Deleted message for trace {trace_id} from queue", trace_id=trace_id)

        except Exception:
            logger.exception("Failed to process EDI message")

            # Message naturally returns to queue for Dead Letter Queue routing
