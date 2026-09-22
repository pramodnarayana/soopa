import asyncio
import contextlib
import signal
import sys

import structlog
from observability import ObservabilityProvider

from identity_worker.bootstrap.container import WorkerContainer
from identity_worker.config.settings import AppSettings

logger = structlog.get_logger(__name__)

from seedwork.infra.worker import LaunchableWorker


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

    async def stop(self) -> None:
        logger.info("identity_worker_shutting_down_tasks")
        if self.container:
            if self.container.events_consumer:
                await self.container.events_consumer.stop()
            await self.container.dispose()
        logger.info("identity_worker_shutdown_complete")


async def main(
    stop_event: asyncio.Event | None = None, settings: AppSettings | None = None
) -> None:
    ObservabilityProvider.auto_configure_from_env("identity-worker")

    module = IdentityWorkerModule(settings=settings)
    try:
        await module.start()

        if stop_event is None:
            stop_event = asyncio.Event()
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                with contextlib.suppress(NotImplementedError, RuntimeError):
                    loop.add_signal_handler(sig, stop_event.set)

        await stop_event.wait()
    finally:
        await module.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
