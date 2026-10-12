import asyncio
import typing

import structlog
from observability import ObservabilityProvider

from edi_dp_jobs_worker.bootstrap.container import WorkerContainer

logger = structlog.get_logger(__name__)


from seedwork.infra.worker import LaunchableWorker, run_worker_app, run_worker_app_async


class EdiDpJobsWorkerModule(LaunchableWorker):
    def __init__(self) -> None:
        self.container = WorkerContainer()
        self.container.wire()

    async def start(self) -> None:
        logger.info("edi_dp_jobs_worker.starting")
        await self.container.start()

    def get_background_tasks(self) -> list[asyncio.Task[object]]:
        if self.container.dp_manager and hasattr(self.container.dp_manager, "background_tasks"):
            return typing.cast(
                list[asyncio.Task[object]], self.container.dp_manager.background_tasks()
            )
        return []

    async def stop(self) -> None:
        logger.info("edi_dp_jobs_worker_shutting_down")
        await self.container.dispose()
        logger.info("edi_dp_jobs_worker_stopped")


async def main(stop_event: asyncio.Event | None = None) -> None:
    ObservabilityProvider.auto_configure_from_env("edi-dp-jobs-worker")
    module = EdiDpJobsWorkerModule()
    await run_worker_app_async(module, stop_event=stop_event)


if __name__ == "__main__":
    run_worker_app(main)
