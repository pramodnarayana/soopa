import asyncio
import signal
import sys
from types import FrameType

import structlog
from observability.config import configure_logging, configure_tracer

from ucp_outbox_worker.bootstrap.container import WorkerContainer

logger = structlog.get_logger(__name__)


async def main() -> None:
    configure_logging()
    configure_tracer("ucp-outbox-worker")

    container = WorkerContainer()
    container.wire()
    logger.info("ucp_outbox_worker_starting")

    shutdown_event = asyncio.Event()

    def handle_sigint(sig: int, frame: FrameType | None) -> None:
        logger.info("received_shutdown_signal")
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)

    tasks: list[asyncio.Task[None]] = []

    if container.outbox_relay:
        relay_task = asyncio.create_task(container.outbox_relay.start())
        tasks.append(relay_task)
    if container.jobs_consumer:
        container.jobs_consumer.start()

    if not tasks:
        logger.warning("no_tasks_configured_for_outbox_worker")
        return

    await shutdown_event.wait()
    logger.info("ucp_outbox_worker_shutting_down")

    if container.jobs_consumer:
        await container.jobs_consumer.stop()
    if container.outbox_relay:
        await container.outbox_relay.stop()

    await asyncio.gather(*tasks, return_exceptions=True)
    await container.dispose()
    logger.info("ucp_outbox_worker_shutdown_complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
