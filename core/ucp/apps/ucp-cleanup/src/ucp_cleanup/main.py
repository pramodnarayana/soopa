import asyncio
import contextlib
import signal

import structlog
from observability import ObservabilityProvider

from ucp_cleanup.bootstrap.container import WorkerContainer

logger = structlog.get_logger(__name__)


async def main() -> None:
    ObservabilityProvider.auto_configure_from_env("ucp-cleanup")
    logger.info("Starting UCP Cleanup Worker...")

    container = WorkerContainer()
    container.wire()

    if container.jobs_consumer:
        container.jobs_consumer.start()
        logger.info("ucp_cleanup_jobs_sqs_consumer_started")

    # We need a stop event to block until shutdown
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, stop_event.set)

    try:
        await stop_event.wait()
    finally:
        logger.info("Shutting down UCP cleanup worker tasks gracefully...")

        if container.jobs_consumer:
            await container.jobs_consumer.stop()

        await container.dispose()


if __name__ == "__main__":
    asyncio.run(main())
