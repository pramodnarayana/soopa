import asyncio
import signal
import sys
from types import FrameType

import structlog
from observability import ObservabilityProvider

from identity_jobs_worker.bootstrap.container import WorkerContainer
from identity_jobs_worker.config.settings import get_settings

logger = structlog.get_logger(__name__)


async def main() -> None:
    settings = get_settings()

    ObservabilityProvider.auto_configure_from_env("identity-jobs-worker")

    container = WorkerContainer(settings)
    container.wire()
    logger.info("identity_jobs_worker_starting")

    shutdown_event = asyncio.Event()

    def handle_sigint(_sig: int, _frame: FrameType | None) -> None:
        logger.info("received_shutdown_signal")
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)

    relay_started = False
    consumer_started = False

    try:
        if container.outbox_relay:
            container.outbox_relay.start()
            relay_started = True
            # The relay starts its own background task. We don't append it to `tasks` directly.
        if container.jobs_consumer:
            container.jobs_consumer.start()
            consumer_started = True

        if not container.outbox_relay and not container.jobs_consumer:
            logger.warning("no_tasks_configured_for_identity_jobs_worker")
            return

        await shutdown_event.wait()
        logger.info("identity_jobs_worker_shutting_down")

    finally:
        if container.jobs_consumer and consumer_started:
            try:
                await container.jobs_consumer.stop()
            except Exception:
                logger.exception("consumer_stop_failed")
        if container.outbox_relay and relay_started:
            try:
                await container.outbox_relay.stop()
            except Exception:
                logger.exception("relay_stop_failed")

        try:
            await container.dispose()
        except Exception:
            logger.exception("container_dispose_failed")
        logger.info("identity_jobs_worker_shutdown_complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
