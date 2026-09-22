import asyncio
import contextlib
import inspect
import signal
from collections.abc import Awaitable
from typing import cast

import structlog
from observability import ObservabilityProvider
from outbox.adapters.inbound.postgres_outbox_relay import PostgresOutboxRelay
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager

from notification_jobs_worker.bootstrap.container import WorkerContainer as Container
from notification_jobs_worker.config.settings import get_settings

logger = structlog.get_logger(__name__)


from seedwork.infra.worker import LaunchableWorker


class NotificationJobsWorkerModule(LaunchableWorker):
    def __init__(self) -> None:
        self.container = Container()
        self.outbox_listener: PostgresOutboxRelay | None = None
        self.jobs_consumer: SqsConsumerManager | None = None

    async def start(self) -> None:
        logger.info("notification_jobs_worker_starting")
        settings = get_settings()

        self.container.config.from_pydantic(settings)
        self.container.config.database_url.from_value(settings.database_url)
        self.container.config.sns_topic_arn.from_value(settings.sns_topic_arn)
        self.container.config.aws_region.from_value(settings.aws_region)
        self.container.config.aws_endpoint_url.from_value(settings.aws_endpoint_url)
        self.container.config.sqs_notification_jobs_queue_url.from_value(
            settings.sqs_notification_jobs_queue_url
        )

        await cast(Awaitable[None], self.container.init_resources())

        self.outbox_listener = self.container.outbox_listener()
        while inspect.isawaitable(self.outbox_listener):
            self.outbox_listener = await self.outbox_listener

        assert self.outbox_listener is not None
        self.outbox_listener.start()
        logger.info("notification_jobs_worker_relay_started")

        self.jobs_consumer = self.container.jobs_consumer()
        while inspect.isawaitable(self.jobs_consumer):
            self.jobs_consumer = await self.jobs_consumer
        assert self.jobs_consumer is not None
        self.jobs_consumer.start()
        logger.info("notification_jobs_worker_consumer_started")

    async def stop(self) -> None:
        logger.info("notification_jobs_worker_shutting_down")
        if self.jobs_consumer:
            with contextlib.suppress(Exception):
                await self.jobs_consumer.stop()
        if self.outbox_listener:
            with contextlib.suppress(Exception):
                await self.outbox_listener.stop()
        await cast(Awaitable[None], self.container.shutdown_resources())


async def main() -> None:
    ObservabilityProvider.auto_configure_from_env("notification-jobs-worker")

    module = NotificationJobsWorkerModule()

    try:
        await module.start()

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, stop_event.set)

        # Supervise the relay task alongside the stop event so relay failures are propagated.
        relay_task: asyncio.Task[object] | None = (
            getattr(module.outbox_listener, "_task", None) if module.outbox_listener else None
        )
        consumer_task: asyncio.Task[object] | None = (
            getattr(module.jobs_consumer, "_task", None) if module.jobs_consumer else None
        )

        tasks_to_wait: list[asyncio.Task[object]] = [asyncio.create_task(stop_event.wait())]
        if relay_task is not None:
            tasks_to_wait.append(relay_task)
        if consumer_task is not None:
            tasks_to_wait.append(consumer_task)

        done, _pending = await asyncio.wait(tasks_to_wait, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            stop_task = tasks_to_wait[0]
            if task is not stop_task and not task.cancelled() and task.exception():
                exc = task.exception()
                logger.error("notification_outbox_relay_or_consumer_failed", exc_info=exc)
                if exc:
                    raise exc
    finally:
        await module.stop()


if __name__ == "__main__":
    asyncio.run(main())
