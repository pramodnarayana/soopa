import asyncio
import contextlib
import signal
from typing import Any

import structlog
from observability import ObservabilityProvider
from ucp.config.settings import get_settings

from ucp_jobs_worker.bootstrap.container import WorkerContainer as Container

logger = structlog.get_logger(__name__)


async def main() -> None:  # noqa: C901
    settings = get_settings()

    ObservabilityProvider.auto_configure_from_env("ucp-jobs-worker")
    logger.info("ucp_jobs_worker.starting")

    container = Container(settings)

    try:
        container.wire()

        if container.outbox_relay:
            container.outbox_relay.start()
            logger.info("ucp_outbox_relay_started")

        if container.jobs_consumer:
            container.jobs_consumer.start()
            logger.info("ucp_jobs_consumer_started")

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, stop_event.set)

        tasks_to_wait: list[asyncio.Task[Any]] = [asyncio.create_task(stop_event.wait())]
        relay_task: asyncio.Task[Any] | None = getattr(container.outbox_relay, "_task", None)
        consumer_task: asyncio.Task[Any] | None = getattr(container.jobs_consumer, "_task", None)

        if relay_task is not None:
            tasks_to_wait.append(relay_task)
        if consumer_task is not None:
            tasks_to_wait.append(consumer_task)

        done, _pending = await asyncio.wait(tasks_to_wait, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            stop_task = tasks_to_wait[0]
            if task is not stop_task and not task.cancelled() and task.exception():
                exc = task.exception()
                logger.error("ucp_jobs_worker_failed", exc_info=exc)
                if exc:
                    raise exc
    finally:
        logger.info("ucp_jobs_worker.shutting_down")
        if container.jobs_consumer:
            with contextlib.suppress(Exception):
                await container.jobs_consumer.stop()
        if container.outbox_relay:
            with contextlib.suppress(Exception):
                await container.outbox_relay.stop()
        await container.dispose()


if __name__ == "__main__":
    asyncio.run(main())
