import asyncio
import json
import logging

from transformer.application.use_cases import ProcessInboundEdiUseCase

logger = logging.getLogger(__name__)


class SQSTransformerWorker:
    """
    Background worker that continuously polls the EdiTransformerQueue
    on AWS SQS and routes messages to the pure Python Use Case.
    """

    def __init__(self, use_case: ProcessInboundEdiUseCase, queue_url: str):
        self.use_case = use_case
        self.queue_url = queue_url
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info(f"Starting SQS worker polling against {self.queue_url}")

        while self._running:
            try:
                # In a real implementation:
                # messages = await sqs_client.receive_message(QueueUrl=self.queue_url)
                # for msg in messages:
                #     await self._process_message(msg)

                # Sleeping to prevent tight loop in stub
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Error in SQS polling loop: {e}")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        logger.info("Stopping SQS worker...")
        self._running = False

    async def _process_message(self, sqs_message: dict[str, object]) -> None:
        """Parses the SQS payload and invokes the pure Domain logic."""
        body_json = json.loads(str(sqs_message.get("Body", "{}")))
        # Extract payload from Debezium/SQS envelope
        trace_id = str(body_json.get("trace_id", "unknown"))
        s3_uri = str(body_json.get("s3_uri", ""))

        logger.info(f"Worker received SQS message for trace {trace_id}")

        try:
            # Execute Hexagonal Use Case
            result = await self.use_case.execute(trace_id=trace_id, s3_uri=s3_uri)
            logger.info(
                f"Successfully transformed EDI into {len(result.transactions)} transactions."
            )

            # sqs_client.delete_message(...)
        except Exception as e:
            logger.error(f"Failed to process EDI trace {trace_id}: {e}")
            # Message naturally returns to queue for Dead Letter Queue routing
