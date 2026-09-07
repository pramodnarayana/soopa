import asyncio
import os
import signal
import sys
from collections.abc import Awaitable
from typing import TypeVar, cast

import structlog
from observability import ObservabilityProvider
from dotenv import load_dotenv
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager

from notification_email_worker.bootstrap.container import WorkerContainer as Container

logger = structlog.get_logger(__name__)


def _setup_container() -> Container:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL is not set")
        sys.exit(1)

    container = Container()
    container.config.database_url.from_value(database_url)
    container.config.email_delivery_queue_url.from_env(
        "SQS_EMAIL_CHANNEL_QUEUE_URL", required=True
    )
    container.config.aws_endpoint_url.from_env("AWS_ENDPOINT_URL")
    container.config.aws_region.from_env("AWS_REGION", default="us-east-1")
    return container


T = TypeVar("T")


async def _resolve_dependency(dep: T | Awaitable[T]) -> T:
    if asyncio.isfuture(dep) or asyncio.iscoroutine(dep):
        return await cast(Awaitable[T], dep)
    return cast(T, dep)


def _setup_signal_handlers(shutdown_event: asyncio.Event) -> None:
    def handle_signal() -> None:
        logger.info("Received termination signal, shutting down workers...")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)


async def _wait_and_handle_errors(
    tasks: list[asyncio.Task[None]], shutdown_task: asyncio.Task[None]
) -> None:
    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in done:
        if task is not shutdown_task:
            exc = task.exception()
            if exc:
                raise exc


async def _graceful_shutdown(
    email_worker: SqsConsumerManager,
    container: Container,
) -> None:
    logger.info("Stopping workers...")
    cleanup_errors: list[BaseException] = []

    try:
        await email_worker.stop()
    except BaseException as exc:
        cleanup_errors.append(exc)
        logger.exception("worker_stop_failed", worker="email_worker")

    try:
        tasks_to_wait = []
        if email_worker.task:
            tasks_to_wait.append(email_worker.task)
        if tasks_to_wait:
            await asyncio.wait_for(asyncio.gather(*tasks_to_wait), timeout=5.0)
    except TimeoutError:
        logger.warning("Tasks did not shut down gracefully")
    except BaseException as exc:
        cleanup_errors.append(exc)
        logger.exception("worker_task_shutdown_failed")

    try:
        await cast(Awaitable[None], container.shutdown_resources())
        logger.info("Container resources shut down successfully.")
    except BaseException as exc:
        cleanup_errors.append(exc)
        logger.exception("container_resource_shutdown_failed")

    if cleanup_errors:
        raise cleanup_errors[0]


async def run_worker(
    stop_event: asyncio.Event | None = None, container: Container | None = None
) -> None:
    dotenv_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../../../../../../.env")
    )
    load_dotenv(dotenv_path)

    if container is None:
        container = _setup_container()

    await cast(Awaitable[None], container.init_resources())

    email_worker = await _resolve_dependency(container.email_worker())

    shutdown_event = stop_event or asyncio.Event()

    if stop_event is None:
        _setup_signal_handlers(shutdown_event)

    ObservabilityProvider.auto_configure_from_env("notification-email-worker")
    logger.info("Starting email delivery worker...")

    email_worker.start()

    async def wait_shutdown() -> None:
        await shutdown_event.wait()

    shutdown_task = asyncio.create_task(wait_shutdown())

    tasks: list[asyncio.Task[None]] = [shutdown_task]
    if email_worker.task:
        tasks.append(email_worker.task)

    try:
        await _wait_and_handle_errors(tasks, shutdown_task)
    finally:
        active_exception = sys.exception()
        try:
            await _graceful_shutdown(email_worker, container)
        except BaseException:
            if active_exception is None:
                raise
            logger.exception("graceful_shutdown_failed_after_worker_error")


if __name__ == "__main__":
    asyncio.run(run_worker())
