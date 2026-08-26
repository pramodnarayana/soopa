from collections.abc import Sequence

import structlog

from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox
from edi.domain.events import PIPELINE_EVENT_ROUTING_MAP
from edi.ports.outbound.edi_data_plane_outbox_publisher_port import (
    EdiDataPlaneOutboxPublisherPort,
    PublishMessageEnvelope,
)

logger = structlog.get_logger(__name__)


class EdiDataPlaneOutboxProcessorUseCase:
    """
    Core Application Service for processing Data Plane Outbox events.
    In the Data Plane, real-time processing is handled by Debezium (CDC).
    This UseCase is primarily leveraged by the Cron Sweeper to process
    batches of stale/pending outbox events as a fallback mechanism.
    """

    MAX_RETRY_ATTEMPTS = 3

    def __init__(self, message_publisher: EdiDataPlaneOutboxPublisherPort) -> None:
        self.message_publisher = message_publisher

    async def process_batch(self, events: Sequence[DataPlaneOutbox]) -> int:  # noqa: C901
        """
        Takes a list of PENDING Data Plane Outbox events, groups them by
        target queue, publishes them via the PublisherPort, and updates
        their status in-memory (the caller is responsible for the DB commit).
        Returns the number of successfully published events.
        """
        if not events:
            return 0

        processed_count = 0
        batches_by_queue: dict[str, list[DataPlaneOutbox]] = {}

        for event in events:
            queue_name = PIPELINE_EVENT_ROUTING_MAP.get(event.event_type)
            if not queue_name:
                logger.warning(
                    "data_plane_outbox.unknown_event_type",
                    event_id=event.id,
                    event_type=event.event_type,
                )
                event.attempts = (event.attempts or 0) + 1
                event.error_reason = f"Unknown event_type: {event.event_type}"
                if event.attempts >= self.MAX_RETRY_ATTEMPTS:
                    event.status = "FAILED"
                else:
                    event.status = "PENDING"
                continue
            batches_by_queue.setdefault(queue_name, []).append(event)

        for queue_name, queue_events in batches_by_queue.items():
            messages = []
            for event in queue_events:
                messages.append(
                    PublishMessageEnvelope(
                        message_id=str(event.id),
                        event_type=event.event_type,
                        event={
                            "payload": event.payload,
                            "tenant_id": event.tenant_id,
                        },
                        idempotency_key=str(event.idempotency_key)
                        if event.idempotency_key
                        else None,
                    )
                )

            try:
                successful_ids = await self.message_publisher.publish_batch(queue_name, messages)
            except Exception as e:
                logger.exception(
                    "data_plane_outbox.publish_batch_failed",
                    queue_name=queue_name,
                    error=str(e),
                )
                successful_ids = []

            for event in queue_events:
                if str(event.id) in successful_ids:
                    event.status = "PROCESSED"
                    processed_count += 1
                else:
                    event.attempts = (event.attempts or 0) + 1
                    event.error_reason = f"Failed to forward to {queue_name}"
                    if event.attempts >= self.MAX_RETRY_ATTEMPTS:
                        event.status = "FAILED"
                    else:
                        event.status = "PENDING"
                    logger.error(
                        "data_plane_outbox.forward_failed",
                        event_id=event.id,
                        queue_name=queue_name,
                        attempts=event.attempts,
                    )

        return processed_count
