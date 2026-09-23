import asyncio
import contextlib
import inspect
import signal
from collections.abc import Awaitable
from typing import cast

import structlog
from observability import ObservabilityProvider
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager

from notification_channel_worker.bootstrap.container import WorkerContainer
from notification_channel_worker.config.settings import get_settings

logger = structlog.get_logger(__name__)


from seedwork.infra.worker import LaunchableWorker


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

    async def stop(self) -> None:
        logger.info("notification_channel_worker_shutting_down")
        for consumer in self.consumers:
            with contextlib.suppress(Exception):
                await consumer.stop()
        await cast(Awaitable[None], self.container.shutdown_resources())


async def main() -> None:
    ObservabilityProvider.auto_configure_from_env("notification-channel-worker")

    module = NotificationChannelWorkerModule()

    try:
        await module.start()

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, stop_event.set)

        stop_task = asyncio.create_task(stop_event.wait())
        wait_tasks: list[asyncio.Task[object]] = [stop_task]
        for consumer in module.consumers:
            if consumer.task is not None:
                wait_tasks.append(consumer.task)

        done, pending = await asyncio.wait(
            wait_tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()

        for consumer in module.consumers:
            if consumer.task is not None and consumer.task in done:
                exc = consumer.task.exception()
                if exc is not None:
                    raise exc
    finally:
        await module.stop()


if __name__ == "__main__":
    asyncio.run(main())
