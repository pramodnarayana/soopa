import asyncio
import contextlib
import signal

import structlog
from observability import ObservabilityProvider

from notification_cleanup.bootstrap.container import WorkerContainer
from notification_cleanup.config.settings import get_settings

logger = structlog.get_logger(__name__)


async def main() -> None:
    settings = get_settings()

    ObservabilityProvider.auto_configure_from_env("notification-cleanup")
    logger.info("notification_cleanup_worker_starting")

    container = WorkerContainer(settings)
    container.wire()

    if container.jobs_consumer:
        container.jobs_consumer.start()
        logger.info("notification_cleanup_jobs_sqs_consumer_started")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, stop_event.set)

    try:
        await stop_event.wait()
    finally:
        logger.info("notification_cleanup_worker_shutting_down")

        if container.jobs_consumer:
            await container.jobs_consumer.stop()

        await container.dispose()


if __name__ == "__main__":
    asyncio.run(main())
