import asyncio
import logging
import os
import signal
import sys
from collections.abc import Awaitable
from typing import cast

from dotenv import load_dotenv

from notification.bootstrap.container import Container

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def run_consumer() -> None:
    dotenv_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../../../../../../.env")
    )
    load_dotenv(dotenv_path)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL is not set")
        sys.exit(1)

    container = Container()
    container.config.database_url.from_value(database_url)
    container.config.sqs_queue_url.from_value(os.environ.get("NOTIFICATION_QUEUE_URL", ""))
    container.config.poll_interval.from_value(
        int(os.environ.get("NOTIF_OUTBOX_POLL_INTERVAL", "2"))
    )

    await cast(Awaitable[None], container.init_resources())

    consumer = container.consumer_worker()

    shutdown_event = asyncio.Event()

    def handle_signal() -> None:
        logger.info("Received termination signal, shutting down consumer...")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)

    logger.info("Starting NotificationConsumerWorker...")
    consumer_task = consumer.start()

    await shutdown_event.wait()

    logger.info("Stopping consumer...")
    await consumer.stop()
    try:
        await asyncio.wait_for(consumer_task, timeout=5.0)
    except TimeoutError:
        logger.warning("Consumer task did not shut down gracefully")

    await cast(Awaitable[None], container.shutdown_resources())
    logger.info("Container resources shut down successfully.")


if __name__ == "__main__":
    asyncio.run(run_consumer())
