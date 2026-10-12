import asyncio

import structlog
from observability import ObservabilityProvider

from identity_jobs_worker.bootstrap.container import WorkerContainer
from identity_jobs_worker.config.settings import get_settings

logger = structlog.get_logger(__name__)


from seedwork.infra.worker import LaunchableWorker, run_worker_app, run_worker_app_async


class IdentityJobsWorkerModule(LaunchableWorker):
    def __init__(self) -> None:
        self.container: WorkerContainer | None = None
        self.relay_started = False
        self.consumer_started = False

    async def start(self) -> None:
        logger.info("identity_jobs_worker_starting")
        settings = get_settings()
        self.container = WorkerContainer(settings)
        self.container.wire()

        if self.container.outbox_relay:
            self.container.outbox_relay.start()
            self.relay_started = True

        if self.container.jobs_consumer:
            self.container.jobs_consumer.start()
            self.consumer_started = True

        if not self.container.outbox_relay and not self.container.jobs_consumer:
            logger.warning("no_tasks_configured_for_identity_jobs_worker")

    def get_background_tasks(self) -> list[asyncio.Task[object]]:
        tasks = []
        if (
            self.container
            and self.container.outbox_relay
            and getattr(self.container.outbox_relay, "task", None)
        ):
            tasks.append(self.container.outbox_relay.task)
        if (
            self.container
            and self.container.jobs_consumer
            and getattr(self.container.jobs_consumer, "task", None)
        ):
            tasks.append(self.container.jobs_consumer.task)
        return tasks

    async def stop(self) -> None:
        logger.info("identity_jobs_worker_shutting_down")
        if self.container:
            if self.container.jobs_consumer and self.consumer_started:
                try:
                    await self.container.jobs_consumer.stop()
                except Exception:
                    logger.exception("consumer_stop_failed")

            if self.container.outbox_relay and self.relay_started:
                try:
                    await self.container.outbox_relay.stop()
                except Exception:
                    logger.exception("relay_stop_failed")

            try:
                await self.container.dispose()
            except Exception:
                logger.exception("container_dispose_failed")

        logger.info("identity_jobs_worker_shutdown_complete")


async def main(stop_event: asyncio.Event | None = None) -> None:
    ObservabilityProvider.auto_configure_from_env("identity-jobs-worker")
    module = IdentityJobsWorkerModule()
    await run_worker_app_async(module, stop_event=stop_event)


if __name__ == "__main__":
    run_worker_app(main)
