import abc

from platform_orm.events import EventEnvelope


class OutboxPublisherPort(abc.ABC):
    """
    Port for publishing outbox events to a message broker (e.g. SNS/SQS).
    """

    @abc.abstractmethod
    async def publish(self, event: EventEnvelope) -> None:
        pass
