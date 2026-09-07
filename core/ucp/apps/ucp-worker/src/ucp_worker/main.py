import asyncio
import contextlib
import signal

import structlog

from ucp_worker.bootstrap.container import WorkerContainer

logger = structlog.get_logger(__name__)


async def main() -> None:
    logger.info("Starting UCP Worker...")

    container = WorkerContainer()
    container.wire()

    if container.events_consumer:
        container.events_consumer.start()
        logger.info("ucp_event_sqs_consumer_started_in_worker")

    # We need a stop event to block until shutdown
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, stop_event.set)

    try:
        await stop_event.wait()
    finally:
        logger.info("Shutting down UCP worker tasks gracefully...")

        if container.events_consumer:
            await container.events_consumer.stop()

        await container.dispose()


if __name__ == "__main__":
    asyncio.run(main())
