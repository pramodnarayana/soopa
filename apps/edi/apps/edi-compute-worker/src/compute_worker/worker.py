import asyncio
import json
import typing
from collections.abc import Awaitable, Callable

import aioboto3
import structlog
from edi.application.use_cases.pipeline.compute_transform_use_case import ComputeTransformUseCase

logger = structlog.get_logger(__name__)


class SQSComputeWorker:
    """
    Background worker that continuously polls the TransformComputeQueue
    on AWS SQS and routes messages to the pure Python Use Case.
    """

    def __init__(
        self,
        use_case_factory: Callable[[str], Awaitable[ComputeTransformUseCase]],
        queue_url: str,
        endpoint_url: str | None = None,
    ):
        self.use_case_factory = use_case_factory
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
            payload = body_json.get("payload", {})
            if not payload:
                # Fallback if the body is already the payload
                payload = body_json

            # Extract and validate required fields
            trace_id = payload.get("trace_id")
            standard = payload.get("standard", "X12")
            transaction_type = payload.get("transaction_type", "UNKNOWN")
            tenant_id = payload.get("tenant_id")

            if not trace_id or not isinstance(trace_id, str) or not trace_id.strip():
                raise ValueError("Required field 'trace_id' is missing or empty")

            if not tenant_id:
                raise ValueError("Required field 'tenant_id' is missing")

            trace_id = str(trace_id).strip()

            logger.info("sqs_message_received", trace_id=trace_id)

            # Execute Hexagonal Use Case dynamically instantiated for the correct Tenant
            use_case = await self.use_case_factory(tenant_id)

            await use_case.execute(
                trace_id=trace_id,
                standard=standard,
                transaction_type=transaction_type
            )

            logger.info("edi_transformed_successfully", trace_id=trace_id)

            # Delete message from queue on success
            receipt_handle = sqs_message.get("ReceiptHandle")
            if receipt_handle:
                await sqs_client.delete_message(
                    QueueUrl=self.queue_url, ReceiptHandle=str(receipt_handle)
                )
                logger.debug("sqs_message_deleted", trace_id=trace_id)

        except Exception:
            logger.exception("edi_message_processing_failed")

            # Message naturally returns to queue for Dead Letter Queue routing
