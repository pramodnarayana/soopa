import asyncio
import contextlib
import inspect
import signal
from collections.abc import Awaitable
from typing import cast

import structlog
from observability import ObservabilityProvider
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager

from notification_worker.bootstrap.container import WorkerContainer as Container
from notification_worker.config.settings import get_settings

logger = structlog.get_logger(__name__)


from seedwork.infra.worker import LaunchableWorker


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

    async def stop(self) -> None:
        logger.info("notification_worker_shutting_down")
        if self.consumer:
            with contextlib.suppress(Exception):
                await self.consumer.stop()
        await cast(Awaitable[None], self.container.shutdown_resources())


async def main() -> None:
    ObservabilityProvider.auto_configure_from_env("notification-worker")

    module = NotificationWorkerModule()

    try:
        await module.start()

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, stop_event.set)

        # Supervise the consumer task alongside the stop event so consumer failures propagate.
        consumer_task: asyncio.Task[object] | None = (
            module.consumer.task if module.consumer else None
        )
        tasks_to_wait: list[asyncio.Task[object]] = [asyncio.create_task(stop_event.wait())]
        if consumer_task is not None:
            tasks_to_wait.append(consumer_task)

        done, _pending = await asyncio.wait(tasks_to_wait, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            stop_task = tasks_to_wait[0]
            if task is not stop_task and not task.cancelled() and task.exception():
                exc = task.exception()
                logger.error("notification_worker_consumer_failed", exc_info=exc)
                if exc:
                    raise exc
    finally:
        await module.stop()


if __name__ == "__main__":
    asyncio.run(main())
