import asyncio
import contextlib
import os

import structlog
from database.provider import DatabaseProvider
from dotenv import load_dotenv
from observability import ObservabilityProvider
from seedwork.infra.worker import LaunchableWorker, run_worker_app, run_worker_app_async

from scheduler_worker.adapters.inbound.workers.scheduler_poller import SchedulerPoller
from scheduler_worker.bootstrap.container import Container
from scheduler_worker.config.settings import get_settings

logger = structlog.get_logger(__name__)

# Hold strong references to background tasks to prevent GC (see RUF006)
_background_tasks: set[asyncio.Task[None]] = set()


class SchedulerWorkerModule(LaunchableWorker):
    def __init__(self) -> None:
        self.container: Container | None = None
        self.db_provider: DatabaseProvider | None = None
        self.worker_task: asyncio.Task[None] | None = None
        self.worker: SchedulerPoller | None = None

    async def start(self) -> None:
        logger.info("scheduler_worker_starting")
        dotenv_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../../../../../../.env")
        )
        load_dotenv(dotenv_path)

        settings = get_settings()

        self.db_provider = DatabaseProvider.from_url(settings.async_database_url)
        self.container = Container(session_factory=self.db_provider.session_factory)
        assert self.container is not None
        self.container.config.from_pydantic(settings)
        self.worker = self.container.worker()
        assert self.worker is not None

        self.worker_task = asyncio.create_task(self.worker.start())
        _background_tasks.add(self.worker_task)
        self.worker_task.add_done_callback(_background_tasks.discard)

    def get_background_tasks(self) -> list[asyncio.Task[object]]:
        if self.worker_task:
            return [self.worker_task]
        return []

    async def stop(self) -> None:
        logger.info("scheduler_worker_stopping")
        try:
            if self.worker:
                await self.worker.stop()
            if self.worker_task:
                with contextlib.suppress(asyncio.CancelledError):
                    await self.worker_task
        finally:
            if self.db_provider:
                await self.db_provider.close()
            logger.info("scheduler_worker_stopped")


async def main(stop_event: asyncio.Event | None = None) -> None:
    ObservabilityProvider.auto_configure_from_env("scheduler-worker")
    module = SchedulerWorkerModule()
    await run_worker_app_async(module, stop_event=stop_event)


if __name__ == "__main__":
    run_worker_app(main)
