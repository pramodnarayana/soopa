import typing

from pubsub.message import AckableMessage


class ConsumerErrorHandlerPort(typing.Protocol):
    """
    Enterprise strategy for handling unhandled exceptions during message consumption.
    Allows injecting different failure policies (e.g., resilient sleep, crash, or DLQ).
    """

    async def handle_error(
        self, error: Exception, ackable_msg: AckableMessage | None, queue_name: str
    ) -> None:
        """Handle the exception that bubbled up from the consumer handler."""
        ...
