import asyncio
import inspect
from collections.abc import Awaitable
from typing import cast

import structlog
from observability import ObservabilityProvider
from outbox.ports.outbox_relay_port import OutboxRelayPort
from pubsub.ports.consumer_manager_port import ConsumerManagerPort
from seedwork.infra.worker import LaunchableWorker, run_worker_app, run_worker_app_async

from notification_jobs_worker.bootstrap.container import WorkerContainer as Container
from notification_jobs_worker.config.settings import get_settings

logger = structlog.get_logger(__name__)


class NotificationJobsWorkerModule(LaunchableWorker):
    def __init__(self) -> None:
        self.container = Container()
        self.outbox_relay: OutboxRelayPort | None = None
        self.jobs_consumer: ConsumerManagerPort | None = None

    async def start(self) -> None:
        logger.info("notification_jobs_worker_starting")
        settings = get_settings()

        self.container.config.from_pydantic(settings)
        self.container.config.database_url.from_value(settings.database_url)
        self.container.config.sns_topic_arn.from_value(settings.sns_topic_arn)
        self.container.config.pubsub_transport.from_value(settings.pubsub_transport)
        self.container.config.aws_region.from_value(settings.aws_region)
        self.container.config.aws_endpoint_url.from_value(settings.aws_endpoint_url)
        self.container.config.sqs_notification_jobs_queue_url.from_value(
            settings.sqs_notification_jobs_queue_url
        )

        await cast(Awaitable[None], self.container.init_resources())

        self.outbox_relay = self.container.outbox_relay()
        while inspect.isawaitable(self.outbox_relay):
            self.outbox_relay = await self.outbox_relay

        assert self.outbox_relay is not None
        self.outbox_relay.start()
        logger.info("notification_jobs_worker_relay_started")

        self.jobs_consumer = self.container.jobs_consumer()
        while inspect.isawaitable(self.jobs_consumer):
            self.jobs_consumer = await self.jobs_consumer
        assert self.jobs_consumer is not None
        self.jobs_consumer.start()
        logger.info("notification_jobs_worker_consumer_started")

    def get_background_tasks(self) -> list[asyncio.Task[object]]:
        tasks: list[asyncio.Task[object]] = []
        if self.outbox_relay is not None:
            tasks.extend(self.outbox_relay.background_tasks())

        if self.jobs_consumer is not None:
            tasks.extend(self.jobs_consumer.background_tasks())
        return tasks

    async def stop(self) -> None:
        logger.info("notification_jobs_worker_shutting_down")
        if self.jobs_consumer:
            try:
                await self.jobs_consumer.stop()
            except Exception:
                logger.exception("notification_jobs_consumer_stop_failed")
        if self.outbox_relay:
            try:
                await self.outbox_relay.stop()
            except Exception:
                logger.exception("notification_outbox_relay_stop_failed")
        await cast(Awaitable[None], self.container.shutdown_resources())


async def main(stop_event: asyncio.Event | None = None) -> None:
    ObservabilityProvider.auto_configure_from_env("notification-jobs-worker")
    module = NotificationJobsWorkerModule()
    await run_worker_app_async(module, stop_event=stop_event)


if __name__ == "__main__":
    run_worker_app(main)
