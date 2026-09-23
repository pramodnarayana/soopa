import asyncio
import signal
import sys
from types import FrameType

import structlog
from observability import ObservabilityProvider

from identity_jobs_worker.bootstrap.container import WorkerContainer
from identity_jobs_worker.config.settings import get_settings

logger = structlog.get_logger(__name__)


from seedwork.infra.worker import LaunchableWorker


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


async def main() -> None:
    ObservabilityProvider.auto_configure_from_env("identity-jobs-worker")

    module = IdentityJobsWorkerModule()

    shutdown_event = asyncio.Event()

    def handle_sigint(_sig: int, _frame: FrameType | None) -> None:
        logger.info("received_shutdown_signal")
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)

    try:
        await module.start()
        await shutdown_event.wait()
    finally:
        await module.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
