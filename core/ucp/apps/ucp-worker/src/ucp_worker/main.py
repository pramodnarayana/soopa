import asyncio
import contextlib
import signal

import structlog
from observability import ObservabilityProvider
from ucp.config.settings import get_settings

from ucp_worker.bootstrap.container import WorkerContainer

logger = structlog.get_logger(__name__)


from seedwork.infra.worker import LaunchableWorker


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

    async def stop(self) -> None:
        logger.info("ucp_worker_shutting_down_tasks")
        if self.container:
            if self.container.events_consumer:
                await self.container.events_consumer.stop()
            await self.container.dispose()
        logger.info("ucp_worker_shutdown_complete")


async def main() -> None:
    ObservabilityProvider.auto_configure_from_env("ucp-worker")

    module = UcpWorkerModule()

    try:
        await module.start()

        # We need a stop event to block until shutdown
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, stop_event.set)

        await stop_event.wait()
    finally:
        await module.stop()


if __name__ == "__main__":
    asyncio.run(main())
