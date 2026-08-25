import asyncio

import structlog

from identity_worker.bootstrap.container import WorkerContainer

logger = structlog.get_logger(__name__)


async def main() -> None:
    logger.info("Starting Identity Worker...")

    container = WorkerContainer()
    container.wire()

    if container.outbox_relay:
        container.outbox_relay.start()
        logger.info("identity_outbox_relay_started_in_worker")

    if container.events_consumer:
        container.events_consumer.start()
        logger.info("sqs_identity_event_consumer_started_in_worker")

    try:
        # Wait forever since we don't have a jobs task to await on yet
        while True:
            await asyncio.sleep(3600)
    finally:
        logger.info("Shutting down Identity worker tasks gracefully...")

        if container.outbox_relay:
            await container.outbox_relay.stop()

        if container.events_consumer:
            await container.events_consumer.stop()

        await container.dispose()


if __name__ == "__main__":
    asyncio.run(main())
