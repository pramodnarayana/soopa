import asyncio
import contextlib
import inspect
import signal
from collections.abc import Awaitable
from typing import Any, cast

import structlog
from observability import ObservabilityProvider

from notification_channel_worker.bootstrap.container import WorkerContainer
from notification_channel_worker.config.settings import get_settings

logger = structlog.get_logger(__name__)


async def main() -> None:  # noqa: C901
    settings = get_settings()

    ObservabilityProvider.auto_configure_from_env("notification-channel-worker")
    logger.info("notification_channel_worker_starting")

    container = WorkerContainer()
    container.config.from_pydantic(settings)

    try:
        await cast(Awaitable[None], container.init_resources())

        email_channel_consumer = container.email_channel_consumer()
        if inspect.isawaitable(email_channel_consumer):
            email_channel_consumer = await email_channel_consumer

        consumers = [email_channel_consumer]

        for consumer in consumers:
            consumer.start()
        logger.info("notification_channel_worker_started", consumers=len(consumers))

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, stop_event.set)

        stop_task = asyncio.create_task(stop_event.wait())
        wait_tasks: list[asyncio.Task[Any]] = [stop_task]
        for consumer in consumers:
            if consumer.task is not None:
                wait_tasks.append(consumer.task)

        done, pending = await asyncio.wait(
            wait_tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()

        for consumer in consumers:
            if consumer.task is not None and consumer.task in done:
                exc = consumer.task.exception()
                if exc is not None:
                    raise exc
    finally:
        logger.info("notification_channel_worker_shutting_down")
        for consumer in consumers:
            with contextlib.suppress(Exception):
                await consumer.stop()
        await cast(Awaitable[None], container.shutdown_resources())


if __name__ == "__main__":
    asyncio.run(main())
