import asyncio
import contextlib
import signal

import structlog

from identity_worker.bootstrap.container import WorkerContainer

logger = structlog.get_logger(__name__)


async def main() -> None:
    logger.info("Starting Identity Worker...")

    container = WorkerContainer()
    try:
        container.wire()

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, stop_event.set)

        if container.outbox_relay:
            container.outbox_relay.start()
            logger.info("identity_outbox_relay_started_in_worker")

        if container.events_consumer:
            container.events_consumer.start()
            logger.info("identity_event_sqs_consumer_started_in_worker")

        await stop_event.wait()
    finally:
        logger.info("Shutting down Identity worker tasks gracefully...")

        if container.outbox_relay:
            await container.outbox_relay.stop()

        if container.events_consumer:
            await container.events_consumer.stop()

        await container.dispose()


if __name__ == "__main__":
    asyncio.run(main())
