import asyncio
import contextlib
import signal
import sys

import structlog
from observability import ObservabilityProvider

from identity_worker.bootstrap.container import WorkerContainer
from identity_worker.config.settings import AppSettings

logger = structlog.get_logger(__name__)


async def main(
    stop_event: asyncio.Event | None = None, settings: AppSettings | None = None
) -> None:
    ObservabilityProvider.auto_configure_from_env("identity-worker")

    logger.info("identity_worker_starting")

    container = WorkerContainer(settings=settings)
    try:
        container.wire()

        if stop_event is None:
            stop_event = asyncio.Event()
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                with contextlib.suppress(NotImplementedError, RuntimeError):
                    loop.add_signal_handler(sig, stop_event.set)

        if container.events_consumer:
            container.events_consumer.start()
            logger.info("identity_event_sqs_consumer_started_in_worker")

        await stop_event.wait()
    finally:
        logger.info("identity_worker_shutting_down_tasks")

        if container.events_consumer:
            await container.events_consumer.stop()

        await container.dispose()
        logger.info("identity_worker_shutdown_complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
