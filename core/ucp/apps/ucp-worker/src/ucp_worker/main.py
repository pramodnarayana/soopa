import asyncio

import structlog
from observability import ObservabilityProvider
from ucp.config.settings import get_settings

from ucp_worker.bootstrap.container import WorkerContainer

logger = structlog.get_logger(__name__)


from seedwork.infra.worker import LaunchableWorker, run_worker_app, run_worker_app_async


class UcpWorkerModule(LaunchableWorker):
    def __init__(self) -> None:
        self.container: WorkerContainer | None = None

    async def start(self) -> None:
        logger.info("ucp_worker_starting")
        settings = get_settings()
        self.container = WorkerContainer(settings)
        self.container.wire()

        if self.container.events_consumer:
            self.container.events_consumer.start()
            logger.info("ucp_event_sqs_consumer_started_in_worker")

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
        logger.info("ucp_worker_shutting_down_tasks")
        if self.container:
            if self.container.events_consumer:
                await self.container.events_consumer.stop()
            await self.container.dispose()
        logger.info("ucp_worker_shutdown_complete")


async def main(stop_event: asyncio.Event | None = None) -> None:
    ObservabilityProvider.auto_configure_from_env("ucp-worker")
    module = UcpWorkerModule()
    await run_worker_app_async(module, stop_event=stop_event)


if __name__ == "__main__":
    run_worker_app(main)
