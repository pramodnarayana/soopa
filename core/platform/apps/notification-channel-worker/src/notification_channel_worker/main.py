import asyncio
import contextlib
import inspect
from collections.abc import Awaitable
from typing import cast

import structlog
from observability import ObservabilityProvider
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager

from notification_channel_worker.bootstrap.container import WorkerContainer
from notification_channel_worker.config.settings import get_settings

logger = structlog.get_logger(__name__)


from seedwork.infra.worker import LaunchableWorker, run_worker_app, run_worker_app_async


class NotificationChannelWorkerModule(LaunchableWorker):
    def __init__(self) -> None:
        self.container = WorkerContainer()
        self.consumers: list[SqsConsumerManager] = []

    async def start(self) -> None:
        logger.info("notification_channel_worker_starting")
        settings = get_settings()

        self.container.config.from_pydantic(settings)

        await cast(Awaitable[None], self.container.init_resources())

        email_consumer = cast(
            Awaitable[SqsConsumerManager] | SqsConsumerManager,
            self.container.email_channel_consumer(),
        )
        if inspect.isawaitable(email_consumer):
            email_consumer = await email_consumer

        self.consumers = [email_consumer]

        for consumer in self.consumers:
            consumer.start()
        logger.info("notification_channel_worker_started", consumers=len(self.consumers))

    def get_background_tasks(self) -> list[asyncio.Task[object]]:
        return [c.task for c in self.consumers if c.task is not None]

    async def stop(self) -> None:
        logger.info("notification_channel_worker_shutting_down")
        for consumer in self.consumers:
            with contextlib.suppress(Exception):
                await consumer.stop()
        await cast(Awaitable[None], self.container.shutdown_resources())


async def main(stop_event: asyncio.Event | None = None) -> None:
    ObservabilityProvider.auto_configure_from_env("notification-channel-worker")
    module = NotificationChannelWorkerModule()
    await run_worker_app_async(module, stop_event=stop_event)


if __name__ == "__main__":
    run_worker_app(main)
