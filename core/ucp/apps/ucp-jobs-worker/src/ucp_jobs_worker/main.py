import asyncio
import contextlib
import signal

import structlog
from observability import ObservabilityProvider
from ucp.config.settings import get_settings

from ucp_jobs_worker.bootstrap.container import WorkerContainer as Container

logger = structlog.get_logger(__name__)


from seedwork.infra.worker import LaunchableWorker


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


async def main() -> None:
    ObservabilityProvider.auto_configure_from_env("ucp-jobs-worker")

    module = UcpJobsWorkerModule()

    try:
        await module.start()

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, stop_event.set)

        tasks_to_wait: list[asyncio.Task[object]] = [asyncio.create_task(stop_event.wait())]
        relay_task: asyncio.Task[object] | None = getattr(
            module.container.outbox_relay, "_task", None
        )
        consumer_task: asyncio.Task[object] | None = getattr(
            module.container.jobs_consumer, "_task", None
        )

        if relay_task is not None:
            tasks_to_wait.append(relay_task)
        if consumer_task is not None:
            tasks_to_wait.append(consumer_task)

        done, _pending = await asyncio.wait(tasks_to_wait, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            stop_task = tasks_to_wait[0]
            if task is not stop_task and not task.cancelled() and task.exception():
                exc = task.exception()
                logger.error("ucp_jobs_worker_failed", exc_info=exc)
                if exc:
                    raise exc
    finally:
        await module.stop()


if __name__ == "__main__":
    asyncio.run(main())
