from collections import defaultdict
from collections.abc import Mapping

import structlog
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from pubsub.aws.aws_sqs_publisher import AwsSqsPublisher
from seedwork.events import EventEnvelope

logger = structlog.get_logger(__name__)


class RoutingSqsPublisher(OutboxPublisherPort):
    """
    Routes outbox events to specific SQS queues based on their event_type.
    This avoids using an SNS fan-out topic for point-to-point Data Plane pipeline routing.
    """

    def __init__(
        self,
        event_type_to_queue_url: Mapping[str, str],
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
    ) -> None:
        self.event_type_to_queue_url = event_type_to_queue_url
        self.publishers: dict[str, AwsSqsPublisher] = {}

        # Initialize publishers for each unique queue URL
        for queue_url in set(event_type_to_queue_url.values()):
            self.publishers[queue_url] = AwsSqsPublisher(
                queue_url=queue_url,
                region_name=region_name,
                endpoint_url=endpoint_url,
            )

    async def publish(self, event: EventEnvelope) -> None:
        published_ids = await self.publish_batch([event])
        if not published_ids:
            raise ValueError(f"Failed to publish event {event.id}")

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        # Group events by their destination queue
        events_by_queue: dict[str, list[EventEnvelope]] = defaultdict(list)
        unroutable_events: list[EventEnvelope] = []

        for event in events:
            queue_url = self.event_type_to_queue_url.get(event.event_type)
            if queue_url:
                events_by_queue[queue_url].append(event)
            else:
                unroutable_events.append(event)

        if unroutable_events:
            logger.error(
                "routing_sqs_publisher.unroutable_events",
                count=len(unroutable_events),
                event_types=list({e.event_type for e in unroutable_events}),
            )
            raise ValueError(
                f"No route found for event types: {list({e.event_type for e in unroutable_events})}"
            )

        # Publish each batch to its respective queue
        message_ids: list[str] = []
        for queue_url, queue_events in events_by_queue.items():
            publisher = self.publishers[queue_url]
            published_ids = await publisher.publish_batch(queue_events)
            message_ids.extend(published_ids)

        return message_ids
