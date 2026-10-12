import asyncio

import structlog
from observability import ObservabilityProvider

from identity_worker.bootstrap.container import WorkerContainer
from identity_worker.config.settings import AppSettings

logger = structlog.get_logger(__name__)

from seedwork.infra.worker import LaunchableWorker, run_worker_app, run_worker_app_async


class IdentityWorkerModule(LaunchableWorker):
    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings
        self.container: WorkerContainer | None = None

    async def start(self) -> None:
        logger.info("identity_worker_starting")
        self.container = WorkerContainer(settings=self.settings)
        self.container.wire()

        if self.container.events_consumer:
            self.container.events_consumer.start()
            logger.info("identity_event_sqs_consumer_started_in_worker")

    def get_background_tasks(self) -> list[asyncio.Task[object]]:
        tasks = []
        if (
            self.container
            and self.container.events_consumer
            and getattr(self.container.events_consumer, "task", None)
        ):
            tasks.append(self.container.events_consumer.task)
        return tasks

    async def stop(self) -> None:
        logger.info("identity_worker_shutting_down_tasks")
        if self.container:
            if self.container.events_consumer:
                await self.container.events_consumer.stop()
            await self.container.dispose()
        logger.info("identity_worker_shutdown_complete")


async def main(
    stop_event: asyncio.Event | None = None,
    settings: AppSettings | None = None,
) -> None:
    ObservabilityProvider.auto_configure_from_env("identity-worker")
    module = IdentityWorkerModule(settings=settings)
    await run_worker_app_async(module, stop_event=stop_event)


if __name__ == "__main__":
    run_worker_app(main)
