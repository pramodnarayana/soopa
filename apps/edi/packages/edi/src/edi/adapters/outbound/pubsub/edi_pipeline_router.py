from collections.abc import Mapping

import structlog
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from seedwork.events import EventEnvelope

logger = structlog.get_logger(__name__)


class UnroutableEventError(Exception):
    """Raised when a pipeline event type has no destination in the EDI pipeline routing table."""

    def __init__(self, event_type: str) -> None:
        super().__init__(f"No route configured for EDI pipeline event type '{event_type}'")
        self.event_type = event_type


class EdiPipelineEventRouter(OutboxPublisherPort):
    """
    EDI pipeline routing policy expressed as an OutboxPublisherPort.

    It owns the knowledge of *which pipeline stage* (orchestrator, compute, deliver)
    receives each ``PipelineEventType``. It is transport-agnostic: every destination is an
    injected ``OutboxPublisherPort``, so the same router works over SQS, Kafka, or an
    in-memory fake without modification.
    """

    def __init__(self, routes: Mapping[str, OutboxPublisherPort]) -> None:
        self._routes = routes

    def _resolve(self, event: EventEnvelope) -> OutboxPublisherPort:
        publisher = self._routes.get(event.event_type)
        if publisher is None:
            raise UnroutableEventError(event.event_type)
        return publisher

    async def publish(self, event: EventEnvelope) -> None:
        await self._resolve(event).publish(event)

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        batches: dict[int, tuple[OutboxPublisherPort, list[EventEnvelope]]] = {}
        for event in events:
            try:
                publisher = self._resolve(event)
            except UnroutableEventError:
                # Not acknowledged: the caller keeps the event pending, so nothing is lost.
                logger.exception(
                    "edi_pipeline_event_unroutable",
                    event_id=event.id,
                    event_type=event.event_type,
                )
                continue
            batches.setdefault(id(publisher), (publisher, []))[1].append(event)

        successful_ids: list[str] = []
        first_transport_error: Exception | None = None
        for publisher, batch in batches.values():
            try:
                successful_ids.extend(await publisher.publish_batch(batch))
            except Exception as exc:
                logger.exception(
                    "edi_pipeline_route_batch_failed",
                    event_count=len(batch),
                )
                first_transport_error = first_transport_error or exc

        if not successful_ids and first_transport_error is not None:
            raise first_transport_error
        return successful_ids
