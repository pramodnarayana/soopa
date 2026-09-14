import asyncio
import signal
import sys
from types import FrameType

import structlog
from observability import ObservabilityProvider
from ucp.config.settings import get_settings

from ucp_outbox_worker.bootstrap.container import WorkerContainer

logger = structlog.get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    ObservabilityProvider.auto_configure_from_env("ucp-outbox-worker")

    container = WorkerContainer(settings)
    container.wire()
    logger.info("ucp_outbox_worker_starting")

    shutdown_event = asyncio.Event()

    def handle_sigint(_sig: int, _frame: FrameType | None) -> None:
        logger.info("received_shutdown_signal")
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)

    if container.outbox_relay:
        container.outbox_relay.start()
    if container.jobs_consumer:
        container.jobs_consumer.start()

    if not container.outbox_relay and not container.jobs_consumer:
        logger.warning("no_tasks_configured_for_outbox_worker")
        return

    await shutdown_event.wait()
    logger.info("ucp_outbox_worker_shutting_down")

    if container.jobs_consumer:
        await container.jobs_consumer.stop()
    if container.outbox_relay:
        await container.outbox_relay.stop()

    await container.dispose()
    logger.info("ucp_outbox_worker_shutdown_complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
