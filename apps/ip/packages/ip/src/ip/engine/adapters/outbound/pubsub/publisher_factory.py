"""Two-Lane Outbox Publisher Router factories for IP Control Plane and Data Plane."""

from __future__ import annotations

import structlog
from ip.engine.domain.enums import IpEventType
from ip.engine.settings import IpEngineSettings
from outbox.adapters.outbound.event_type_router import EventTypeOutboxRouter, RouteKey
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from seedwork.events import EventEnvelope, EventProcessingLane

from pubsub.provider import PubSubProvider

logger = structlog.get_logger(__name__)

NOTIFICATION_REQUESTED_EVENT_TYPE = "notification.requested"


class _UnconfiguredOutboxPublisher(OutboxPublisherPort):
    """Fallback publisher used when a queue URL or topic ARN is not configured in settings."""

    def __init__(self, target_name: str = "unconfigured") -> None:
        self._target_name = target_name

    async def publish(self, event: EventEnvelope) -> None:
        logger.info(
            "ip_outbox_unconfigured_publisher_event_skipped",
            target=self._target_name,
            event_id=event.id,
            event_type=event.event_type,
            lane=event.lane,
            tenant_id=event.tenant_id,
        )

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        if events:
            logger.info(
                "ip_outbox_unconfigured_publisher_batch_skipped",
                target=self._target_name,
                batch_size=len(events),
                event_types=sorted({e.event_type for e in events}),
            )
        return [e.id for e in events]


def _queue_or_noop(
    queue_url: str, settings: IpEngineSettings, target_name: str = "sqs_queue"
) -> OutboxPublisherPort:
    if not queue_url:
        return _UnconfiguredOutboxPublisher(target_name=target_name)
    return PubSubProvider.create_queue_publisher(
        queue_url=queue_url,
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    )


def _topic_or_noop(
    topic_arn: str, settings: IpEngineSettings, target_name: str = "sns_topic"
) -> OutboxPublisherPort:
    if not topic_arn:
        return _UnconfiguredOutboxPublisher(target_name=target_name)
    return PubSubProvider.create_topic_publisher(
        topic_arn=topic_arn,
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    )


def build_ip_cp_outbox_router(
    *,
    orchestrator_realtime_publisher: OutboxPublisherPort,
    orchestrator_bulk_publisher: OutboxPublisherPort,
    delivery_realtime_publisher: OutboxPublisherPort,
    delivery_bulk_publisher: OutboxPublisherPort,
    notification_publisher: OutboxPublisherPort,
    events_topic_publisher: OutboxPublisherPort,
) -> EventTypeOutboxRouter:
    """Assembles the Two-Lane EventTypeOutboxRouter for IP Control Plane (`ip.outbox`)."""
    routes: dict[RouteKey, OutboxPublisherPort] = {
        (
            IpEventType.TRANSFORMATION_CHANGED,
            EventProcessingLane.REALTIME,
        ): orchestrator_realtime_publisher,
        (IpEventType.TRANSFORMATION_CHANGED, EventProcessingLane.BULK): orchestrator_bulk_publisher,
        (
            IpEventType.TRANSFORMATION_VERSION_PROMOTED,
            EventProcessingLane.REALTIME,
        ): orchestrator_realtime_publisher,
        (
            IpEventType.TRANSFORMATION_VERSION_PROMOTED,
            EventProcessingLane.BULK,
        ): orchestrator_bulk_publisher,
        (
            IpEventType.GENERATION_COMPLETED,
            EventProcessingLane.REALTIME,
        ): orchestrator_realtime_publisher,
        (IpEventType.GENERATION_COMPLETED, EventProcessingLane.BULK): orchestrator_bulk_publisher,
        (IpEventType.SYNC_RUN_REQUESTED, EventProcessingLane.REALTIME): delivery_realtime_publisher,
        (IpEventType.SYNC_RUN_REQUESTED, EventProcessingLane.BULK): delivery_bulk_publisher,
        NOTIFICATION_REQUESTED_EVENT_TYPE: notification_publisher,
    }
    return EventTypeOutboxRouter(
        routes=routes,
        default_publisher=events_topic_publisher,
    )


def build_ip_dp_outbox_router(
    *,
    orchestrator_realtime_publisher: OutboxPublisherPort,
    orchestrator_bulk_publisher: OutboxPublisherPort,
    delivery_realtime_publisher: OutboxPublisherPort,
    delivery_bulk_publisher: OutboxPublisherPort,
    notification_publisher: OutboxPublisherPort,
    events_topic_publisher: OutboxPublisherPort,
) -> EventTypeOutboxRouter:
    """Assembles the Two-Lane EventTypeOutboxRouter for IP Data Plane (`public.ip_outbox`)."""
    routes: dict[RouteKey, OutboxPublisherPort] = {
        (
            IpEventType.INBOUND_RECORD_CREATED,
            EventProcessingLane.REALTIME,
        ): orchestrator_realtime_publisher,
        (IpEventType.INBOUND_RECORD_CREATED, EventProcessingLane.BULK): orchestrator_bulk_publisher,
        (
            IpEventType.REPLICA_RECORD_CHANGED,
            EventProcessingLane.REALTIME,
        ): orchestrator_realtime_publisher,
        (IpEventType.REPLICA_RECORD_CHANGED, EventProcessingLane.BULK): orchestrator_bulk_publisher,
        (
            IpEventType.NORMALIZED_RECORD_CREATED,
            EventProcessingLane.REALTIME,
        ): orchestrator_realtime_publisher,
        (
            IpEventType.NORMALIZED_RECORD_CREATED,
            EventProcessingLane.BULK,
        ): orchestrator_bulk_publisher,
        (
            IpEventType.CANONICAL_RECORD_CHANGED,
            EventProcessingLane.REALTIME,
        ): orchestrator_realtime_publisher,
        (
            IpEventType.CANONICAL_RECORD_CHANGED,
            EventProcessingLane.BULK,
        ): orchestrator_bulk_publisher,
        (
            IpEventType.OUTBOUND_RECORD_CREATED,
            EventProcessingLane.REALTIME,
        ): delivery_realtime_publisher,
        (IpEventType.OUTBOUND_RECORD_CREATED, EventProcessingLane.BULK): delivery_bulk_publisher,
        (
            IpEventType.FETCH_RECORD_REQUESTED,
            EventProcessingLane.REALTIME,
        ): delivery_realtime_publisher,
        (IpEventType.FETCH_RECORD_REQUESTED, EventProcessingLane.BULK): delivery_bulk_publisher,
        NOTIFICATION_REQUESTED_EVENT_TYPE: notification_publisher,
    }
    return EventTypeOutboxRouter(
        routes=routes,
        default_publisher=events_topic_publisher,
    )


def create_ip_cp_outbox_publisher(settings: IpEngineSettings) -> EventTypeOutboxRouter:
    """Creates the production IP Control Plane outbox publisher router from IpEngineSettings."""
    return build_ip_cp_outbox_router(
        orchestrator_realtime_publisher=_queue_or_noop(
            settings.ip_orchestrator_realtime_queue_url, settings
        ),
        orchestrator_bulk_publisher=_queue_or_noop(
            settings.ip_orchestrator_bulk_queue_url, settings
        ),
        delivery_realtime_publisher=_queue_or_noop(
            settings.ip_delivery_realtime_queue_url, settings
        ),
        delivery_bulk_publisher=_queue_or_noop(settings.ip_delivery_bulk_queue_url, settings),
        notification_publisher=_queue_or_noop(settings.notification_queue_url, settings),
        events_topic_publisher=_topic_or_noop(settings.ip_events_topic_arn, settings),
    )


def create_ip_dp_outbox_publisher(settings: IpEngineSettings) -> EventTypeOutboxRouter:
    """Creates the production IP Data Plane outbox publisher router from IpEngineSettings."""
    return build_ip_dp_outbox_router(
        orchestrator_realtime_publisher=_queue_or_noop(
            settings.ip_orchestrator_realtime_queue_url, settings
        ),
        orchestrator_bulk_publisher=_queue_or_noop(
            settings.ip_orchestrator_bulk_queue_url, settings
        ),
        delivery_realtime_publisher=_queue_or_noop(
            settings.ip_delivery_realtime_queue_url, settings
        ),
        delivery_bulk_publisher=_queue_or_noop(settings.ip_delivery_bulk_queue_url, settings),
        notification_publisher=_queue_or_noop(settings.notification_queue_url, settings),
        events_topic_publisher=_topic_or_noop(settings.ip_events_topic_arn, settings),
    )


__all__ = [
    "NOTIFICATION_REQUESTED_EVENT_TYPE",
    "build_ip_cp_outbox_router",
    "build_ip_dp_outbox_router",
    "create_ip_cp_outbox_publisher",
    "create_ip_dp_outbox_publisher",
]
