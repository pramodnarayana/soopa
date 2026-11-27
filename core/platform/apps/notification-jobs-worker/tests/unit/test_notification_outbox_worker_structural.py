import inspect
from collections.abc import Awaitable
from typing import cast

import pytest
from notification.domain.constants import NotificationOutboxSource
from outbox.adapters.inbound.outbox_drain_relay import OutboxDrainRelay

from notification_jobs_worker.bootstrap.container import WorkerContainer


@pytest.mark.asyncio
async def test_structural() -> None:
    container = WorkerContainer()
    container.config.database_url.from_value("sqlite+aiosqlite:///:memory:")
    container.config.sns_topic_arn.from_value("db://platform-events-topic")
    container.config.pubsub_transport.from_value("db")
    container.config.aws_region.from_value("us-east-1")
    container.config.aws_endpoint_url.from_value(None)
    container.config.sqs_notification_jobs_queue_url.from_value("db://notification-jobs-queue")

    await cast(Awaitable[None], container.init_resources())
    try:
        relay = container.outbox_relay()
        while inspect.isawaitable(relay):
            relay = await relay
        assert isinstance(relay, OutboxDrainRelay)
        assert relay.relay_name == NotificationOutboxSource.NOTIFICATION.value
    finally:
        await cast(Awaitable[None], container.shutdown_resources())
