import asyncio
import os
import signal
import sys
from collections.abc import Awaitable
from typing import Any, cast

import structlog
from dotenv import load_dotenv

from notification_worker.bootstrap.container import WorkerContainer as Container

logger = structlog.get_logger(__name__)


async def run_consumer(  # noqa: C901
    stop_event: asyncio.Event | None = None, container: Container | None = None
) -> None:
    dotenv_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../../../../../../.env")
    )
    load_dotenv(dotenv_path)

    if container is None:
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
        container.config.priority_queue_url.from_env(
            "SQS_PRIORITY_NOTIFICATIONS_QUEUE_URL", required=True
        )
        container.config.email_delivery_queue_url.from_env(
            "SQS_EMAIL_DELIVERY_QUEUE_URL", required=True
        )
        container.config.aws_endpoint_url.from_env("AWS_ENDPOINT_URL")
        container.config.aws_region.from_env("AWS_REGION", default="us-east-1")

    await cast(Awaitable[None], container.init_resources())

    consumer = container.consumer_worker()
    if asyncio.isfuture(consumer) or asyncio.iscoroutine(consumer):
        consumer = await consumer

    email_worker = container.email_worker()
    if asyncio.isfuture(email_worker) or asyncio.iscoroutine(email_worker):
        email_worker = await email_worker

    outbox_listener = container.outbox_listener()
    if asyncio.isfuture(outbox_listener) or asyncio.iscoroutine(outbox_listener):
        outbox_listener = await outbox_listener

    shutdown_event = stop_event or asyncio.Event()

    if stop_event is None:

        def handle_signal() -> None:
            logger.info("Received termination signal, shutting down workers...")
            shutdown_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handle_signal)

    logger.info("Starting workers...")

    # 1. Compiler Worker (Stage 2)
    consumer.start()

    # 2. Email Delivery Worker (Stage 3)
    email_worker.start()

    # 3. Outbox Relay
    outbox_listener.start()

    shutdown_task = asyncio.create_task(shutdown_event.wait())

    tasks: list[asyncio.Task[Any]] = [cast(asyncio.Task[Any], shutdown_task)]
    if consumer.task:
        tasks.append(cast(asyncio.Task[Any], consumer.task))
    if email_worker.task:
        tasks.append(cast(asyncio.Task[Any], email_worker.task))

    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    for task in done:
        if task is not shutdown_task:
            exc = task.exception()
            if exc:
                raise exc

    logger.info("Stopping workers...")
    await outbox_listener.stop()
    await consumer.stop()
    await email_worker.stop()

    try:
        tasks_to_wait = []
        if consumer.task:
            tasks_to_wait.append(consumer.task)
        if email_worker.task:
            tasks_to_wait.append(email_worker.task)
        if tasks_to_wait:
            await asyncio.wait_for(asyncio.gather(*tasks_to_wait), timeout=5.0)
    except TimeoutError:
        logger.warning("Tasks did not shut down gracefully")

    await cast(Awaitable[None], container.shutdown_resources())
    logger.info("Container resources shut down successfully.")


if __name__ == "__main__":
    asyncio.run(run_consumer())
