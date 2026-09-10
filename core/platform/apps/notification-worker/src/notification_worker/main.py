import asyncio
import contextlib
import inspect
import signal
from collections.abc import Awaitable
from typing import cast

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

    try:
        await stop_event.wait()
    finally:
        logger.info("notification_worker_shutting_down")
        await consumer.stop()
        await cast(Awaitable[None], container.shutdown_resources())


if __name__ == "__main__":
    asyncio.run(main())
