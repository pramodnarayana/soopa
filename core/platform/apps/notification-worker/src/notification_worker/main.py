import asyncio
import contextlib
import inspect
import signal
from collections.abc import Awaitable
from typing import Any, cast

import structlog
from observability import ObservabilityProvider

from notification_worker.bootstrap.container import WorkerContainer as Container
from notification_worker.config.settings import get_settings

logger = structlog.get_logger(__name__)


async def main() -> None:
    settings = get_settings()

    ObservabilityProvider.auto_configure_from_env("notification-worker")
    logger.info("notification_worker_starting")

    container = Container()
    container.config.from_pydantic(settings)
    container.config.database_url.from_value(settings.database_url)
    container.config.sqs_priority_notifications_queue_url.from_value(
        settings.sqs_priority_notifications_queue_url
    )
    container.config.aws_region.from_value(settings.aws_region)
    container.config.aws_endpoint_url.from_value(settings.aws_endpoint_url)

    try:
        await cast(Awaitable[None], container.init_resources())

        consumer = container.consumer_worker()
        if inspect.isawaitable(consumer):
            consumer = await consumer

        consumer.start()
        logger.info("notification_worker_consumer_started")

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, stop_event.set)

        # Supervise the consumer task alongside the stop event so consumer failures propagate.
        consumer_task: asyncio.Task[Any] | None = consumer.task
        tasks_to_wait: list[asyncio.Task[Any]] = [asyncio.create_task(stop_event.wait())]
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
        logger.info("notification_worker_shutting_down")
        with contextlib.suppress(Exception):
            await consumer.stop()
        await cast(Awaitable[None], container.shutdown_resources())


if __name__ == "__main__":
    asyncio.run(main())
