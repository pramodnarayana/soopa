import asyncio
import contextlib
import inspect
from collections.abc import Awaitable
from typing import cast

import structlog
from observability import ObservabilityProvider
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager

from notification_worker.bootstrap.container import WorkerContainer as Container
from notification_worker.config.settings import get_settings

logger = structlog.get_logger(__name__)


from seedwork.infra.worker import LaunchableWorker, run_worker_app, run_worker_app_async


class NotificationWorkerModule(LaunchableWorker):
    def __init__(self) -> None:
        self.container = Container()
        self.consumer: SqsConsumerManager | None = None

    async def start(self) -> None:
        logger.info("notification_worker_starting")
        settings = get_settings()

        self.container.config.from_pydantic(settings)
        self.container.config.database_url.from_value(settings.database_url)
        self.container.config.sqs_priority_notifications_queue_url.from_value(
            settings.sqs_priority_notifications_queue_url
        )
        self.container.config.aws_region.from_value(settings.aws_region)
        self.container.config.aws_endpoint_url.from_value(settings.aws_endpoint_url)

        await cast(Awaitable[None], self.container.init_resources())

        self.consumer = self.container.consumer_worker()
        if inspect.isawaitable(self.consumer):
            self.consumer = await self.consumer

        assert self.consumer is not None
        self.consumer.start()
        logger.info("notification_worker_consumer_started")

    def get_background_tasks(self) -> list[asyncio.Task[object]]:
        if self.consumer and self.consumer.task:
            return [self.consumer.task]
        return []

    async def stop(self) -> None:
        logger.info("notification_worker_shutting_down")
        if self.consumer:
            with contextlib.suppress(Exception):
                await self.consumer.stop()
        await cast(Awaitable[None], self.container.shutdown_resources())


async def main(stop_event: asyncio.Event | None = None) -> None:
    ObservabilityProvider.auto_configure_from_env("notification-worker")
    module = NotificationWorkerModule()
    await run_worker_app_async(module, stop_event=stop_event)


if __name__ == "__main__":
    run_worker_app(main)
