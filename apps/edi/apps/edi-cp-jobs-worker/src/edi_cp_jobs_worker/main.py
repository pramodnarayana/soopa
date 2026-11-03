import asyncio

import structlog
from observability import ObservabilityProvider
from seedwork.infra.worker import LaunchableWorker, run_worker_app, run_worker_app_async

from edi_cp_jobs_worker.bootstrap.container import WorkerContainer

logger = structlog.get_logger(__name__)


class EdiCpJobsWorkerModule(LaunchableWorker):
    def __init__(self) -> None:
        self.container = WorkerContainer()
        self.container.wire()

    async def start(self) -> None:
        logger.info("edi_cp_jobs_worker.starting")
        await self.container.start()

    def get_background_tasks(self) -> list[asyncio.Task[object]]:
        tasks: list[asyncio.Task[object]] = []
        if self.container.cp_manager is not None:
            tasks.extend(self.container.cp_manager.background_tasks())
        if self.container.cp_outbox_relay is not None:
            tasks.extend(self.container.cp_outbox_relay.background_tasks())
        return tasks

    async def stop(self) -> None:
        logger.info("edi_cp_jobs_worker_shutting_down")
        await self.container.dispose()
        logger.info("edi_cp_jobs_worker_stopped")


async def main(stop_event: asyncio.Event | None = None) -> None:
    ObservabilityProvider.auto_configure_from_env("edi-cp-jobs-worker")
    module = EdiCpJobsWorkerModule()
    await run_worker_app_async(module, stop_event=stop_event)


if __name__ == "__main__":
    run_worker_app(main)
