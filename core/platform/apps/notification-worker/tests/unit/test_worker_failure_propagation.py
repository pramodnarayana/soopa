from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from notification_worker.adapters.inbound.workers.email_channel_sqs_consumer import (
    EmailChannelSqsConsumer,
)
from notification_worker.adapters.inbound.workers.notification_event_sqs_consumer import (
    NotificationEventSqsConsumer,
)


class FailingSqsConsumer:
    queue_name = "failing-queue"

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        return None

    @asynccontextmanager
    async def poll_raw_message(self) -> AsyncIterator[dict | None]:
        raise RuntimeError("poll failed")
        yield None


class UnusedDependency:
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize("consumer_type", [EmailChannelSqsConsumer, NotificationEventSqsConsumer])
async def test_poll_failure_propagates_from_worker_run(consumer_type) -> None:
    if consumer_type is EmailChannelSqsConsumer:
        worker = consumer_type(
            consumer=FailingSqsConsumer(),
            email_strategy=UnusedDependency(),
        )
    else:
        worker = consumer_type(
            consumer=FailingSqsConsumer(),
            notification_compiler=UnusedDependency(),
            cleanup_job_handler=UnusedDependency(),
        )

    with pytest.raises(RuntimeError, match="poll failed"):
        await worker._run()
