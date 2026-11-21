"""Default consumer error handlers for AWS adapters."""

from __future__ import annotations

import asyncio

import structlog

from pubsub.domain.dtos import AckableMessage
from pubsub.ports.consumer_error_handler_port import ConsumerErrorHandlerPort

logger = structlog.get_logger(__name__)


class DefaultConsumerErrorHandler(ConsumerErrorHandlerPort):
    """
    Standard production strategy for handling message consumer errors.
    Logs the exception, NACKs the message for retry, and briefly sleeps
    to prevent tight infinite loops on fast, recurring failures.
    """

    def __init__(self, error_sleep_seconds: float = 5.0) -> None:
        self.error_sleep_seconds = error_sleep_seconds

    async def handle_error(
        self, error: Exception, ackable_msg: AckableMessage | None, queue_name: str
    ) -> None:
        logger.exception("sqs_consumer_manager_unhandled_fatal_error", queue=queue_name)

        if ackable_msg:
            await ackable_msg.nack()
        await asyncio.sleep(self.error_sleep_seconds)
