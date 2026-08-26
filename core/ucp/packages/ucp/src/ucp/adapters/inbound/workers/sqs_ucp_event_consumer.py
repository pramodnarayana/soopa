from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer

from ucp.ports.outbound.ucp_event_consumer_port import UcpEventConsumerPort, UcpEventMessage

logger = structlog.get_logger(__name__)


class SqsUcpEventConsumer(UcpEventConsumerPort):
    """
    AWS SQS Adapter for consuming UCP events from a queue.
    Delegates the raw aioboto3 polling to the generic AwsSqsConsumer.
    """

    def __init__(
        self,
        queue_name: str,
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
    ):
        self._consumer = AwsSqsConsumer(
            queue_name=queue_name,
            region_name=region_name,
            endpoint_url=endpoint_url,
        )

    async def __aenter__(self) -> "SqsUcpEventConsumer":
        await self._consumer.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self._consumer.__aexit__(exc_type, exc_val, exc_tb)

    @asynccontextmanager
    async def process_next_event(self) -> AsyncGenerator[UcpEventMessage | None, None]:
        async with self._consumer.poll_raw_message() as raw_msg:
            if not raw_msg:
                yield None
                return

            try:
                event_message = UcpEventMessage.model_validate(raw_msg)
            except Exception:
                logger.exception("ucp_event_validation_failed")
                # Raise the exception so the underlying AwsSqsConsumer skips deletion
                # and SQS can eventually route this poison pill to the DLQ.
                raise

            yield event_message
