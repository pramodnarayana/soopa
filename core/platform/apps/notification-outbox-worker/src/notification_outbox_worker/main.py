import asyncio
import contextlib
import inspect
import signal
from collections.abc import Awaitable
from typing import cast

import structlog
from observability import ObservabilityProvider

from notification_outbox_worker.bootstrap.container import WorkerContainer as Container
from notification_outbox_worker.config.settings import get_settings

logger = structlog.get_logger(__name__)


async def main() -> None:
    settings = get_settings()

    ObservabilityProvider.auto_configure_from_env("notification-outbox-worker")
    logger.info("notification_outbox_worker_starting")

    container = Container()
    container.config.from_pydantic(settings)
    await cast(Awaitable[None], container.init_resources())

    outbox_listener = container.outbox_listener()
    if inspect.isawaitable(outbox_listener):
        outbox_listener = await outbox_listener

    outbox_listener.start()
    logger.info("notification_outbox_worker_relay_started")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, stop_event.set)

    try:
        await stop_event.wait()
    finally:
        logger.info("notification_outbox_worker_shutting_down")
        await outbox_listener.stop()
        await cast(Awaitable[None], container.shutdown_resources())


if __name__ == "__main__":
    asyncio.run(main())
