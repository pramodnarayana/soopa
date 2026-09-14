import asyncio
import contextlib
import inspect
import signal
from collections.abc import Awaitable
from typing import Any, cast

import structlog
from observability import ObservabilityProvider

from notification_email_worker.bootstrap.container import WorkerContainer
from notification_email_worker.config.settings import get_settings

logger = structlog.get_logger(__name__)


async def main() -> None:
    settings = get_settings()

    ObservabilityProvider.auto_configure_from_env("notification-email-worker")
    logger.info("notification_email_worker_starting")

    container = WorkerContainer()
    container.config.from_pydantic(settings)

    try:
        await cast(Awaitable[None], container.init_resources())

        email_worker = container.email_worker()
        if inspect.isawaitable(email_worker):
            email_worker = await email_worker

        email_worker.start()
        logger.info("notification_email_worker_started")

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, stop_event.set)

        stop_task = asyncio.create_task(stop_event.wait())
        wait_tasks: list[asyncio.Task[Any]] = [stop_task]
        if email_worker.task is not None:
            wait_tasks.append(email_worker.task)

        done, pending = await asyncio.wait(
            wait_tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()

        if email_worker.task is not None and email_worker.task in done:
            exc = email_worker.task.exception()
            if exc is not None:
                raise exc
    finally:
        logger.info("notification_email_worker_shutting_down")
        with contextlib.suppress(Exception):
            await email_worker.stop()
        await cast(Awaitable[None], container.shutdown_resources())


if __name__ == "__main__":
    asyncio.run(main())
