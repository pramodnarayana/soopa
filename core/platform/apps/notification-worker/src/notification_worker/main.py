import asyncio
import os
import signal
import sys
from collections.abc import Awaitable
from typing import cast

import structlog
from dotenv import load_dotenv

from notification_worker.bootstrap.container import WorkerContainer as Container

logger = structlog.get_logger(__name__)


async def run_consumer() -> None:
    dotenv_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../../../../../../.env")
    )
    load_dotenv(dotenv_path)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL is not set")
        sys.exit(1)

    sns_topic_arn = os.environ.get("SNS_TOPIC_ARN")
    if not sns_topic_arn:
        logger.error("SNS_TOPIC_ARN is not set")
        sys.exit(1)

    container = Container()
    container.config.database_url.from_value(database_url)
    container.config.sns_topic_arn.from_value(sns_topic_arn)

    await cast(Awaitable[None], container.init_resources())

    consumer = container.consumer_worker()
    email_worker = container.email_worker()
    outbox_listener = container.outbox_listener()

    shutdown_event = asyncio.Event()

    def handle_signal() -> None:
        logger.info("Received termination signal, shutting down workers...")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)

    logger.info("Starting workers...")

    # 1. Compiler Worker (Stage 2)
    consumer_task = consumer.start()

    # 2. Email Delivery Worker (Stage 3)
    email_task = email_worker.start()

    # 3. Outbox Relay
    outbox_listener.start()

    shutdown_task = asyncio.create_task(shutdown_event.wait())

    done, _ = await asyncio.wait(
        [shutdown_task, consumer_task, email_task], return_when=asyncio.FIRST_COMPLETED
    )

    for task in done:
        if task is not shutdown_task:
            task.result()

    logger.info("Stopping workers...")
    await outbox_listener.stop()
    await consumer.stop()
    await email_worker.stop()

    try:
        await asyncio.wait_for(asyncio.gather(consumer_task, email_task), timeout=5.0)
    except TimeoutError:
        logger.warning("Tasks did not shut down gracefully")

    await cast(Awaitable[None], container.shutdown_resources())
    logger.info("Container resources shut down successfully.")


if __name__ == "__main__":
    asyncio.run(run_consumer())
