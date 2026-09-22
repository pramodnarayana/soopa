import asyncio
import contextlib
import os
import signal
import sys

import structlog
from observability import ObservabilityProvider
from unified_worker.registry import get_worker_instance

logger = structlog.get_logger(__name__)


async def main(stop_event: asyncio.Event | None = None) -> None:
    ObservabilityProvider.auto_configure_from_env("unified-worker")
    logger.info("unified_worker_starting")

    worker_modules_env = os.environ.get("WORKER_MODULES", "")
    if not worker_modules_env:
        logger.error("No WORKER_MODULES environment variable provided. Exiting.")
        sys.exit(1)

    module_names = [name.strip() for name in worker_modules_env.split(",") if name.strip()]
    if not module_names:
        logger.error("WORKER_MODULES environment variable is empty after parsing. Exiting.")
        sys.exit(1)

    workers = []
    for name in module_names:
        worker_instance = get_worker_instance(name)
        workers.append((name, worker_instance))

    if stop_event is None:
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, stop_event.set)

    logger.info("starting_workers", count=len(workers), workers=module_names)

    # Start all workers concurrently
    start_tasks = [worker.start() for _, worker in workers]
    await asyncio.gather(*start_tasks)

    logger.info("all_workers_started_successfully")

    # Wait for termination signal
    await stop_event.wait()

    logger.info("unified_worker_shutting_down")

    # Stop all workers concurrently
    stop_tasks = [worker.stop() for _, worker in workers]
    await asyncio.gather(*stop_tasks, return_exceptions=True)

    logger.info("unified_worker_shutdown_complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
