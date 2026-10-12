import asyncio

import structlog
from observability import ObservabilityProvider
from ucp.config.settings import get_settings

from ucp_jobs_worker.bootstrap.container import WorkerContainer as Container

logger = structlog.get_logger(__name__)


from seedwork.infra.worker import LaunchableWorker, run_worker_app, run_worker_app_async


class UcpJobsWorkerModule(LaunchableWorker):
    def __init__(self) -> None:
        self.container = Container(get_settings())

    async def start(self) -> None:
        logger.info("ucp_jobs_worker.starting")
        self.container.wire()

        if self.container.outbox_relay:
            self.container.outbox_relay.start()
            logger.info("ucp_outbox_relay_started")

        if self.container.jobs_consumer:
            self.container.jobs_consumer.start()
            logger.info("ucp_jobs_consumer_started")

    def get_background_tasks(self) -> list[asyncio.Task[object]]:
        tasks = []
        if self.container.outbox_relay and getattr(self.container.outbox_relay, "task", None):
            tasks.append(self.container.outbox_relay.task)
        if self.container.jobs_consumer and getattr(self.container.jobs_consumer, "task", None):
            tasks.append(self.container.jobs_consumer.task)
        return tasks

    async def stop(self) -> None:
        logger.info("ucp_jobs_worker.shutting_down")
        if self.container.jobs_consumer:
            try:
                await self.container.jobs_consumer.stop()
            except Exception:
                logger.exception("consumer_stop_failed")
        if self.container.outbox_relay:
            try:
                await self.container.outbox_relay.stop()
            except Exception:
                logger.exception("relay_stop_failed")
        try:
            await self.container.dispose()
        except Exception:
            logger.exception("container_dispose_failed")


async def main(stop_event: asyncio.Event | None = None) -> None:
    ObservabilityProvider.auto_configure_from_env("ucp-jobs-worker")
    module = UcpJobsWorkerModule()
    await run_worker_app_async(module, stop_event=stop_event)


if __name__ == "__main__":
    run_worker_app(main)
