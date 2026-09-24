import asyncio
import contextlib
import os
import signal
import sys
from typing import Any

import structlog
from observability import ObservabilityProvider
from unified_worker.registry import get_worker_instance

logger = structlog.get_logger(__name__)


async def _start_workers(workers: list[tuple[str, Any]]) -> list[Any]:
    started_workers = []
    start_tasks = [worker.start() for _, worker in workers]
    results = await asyncio.gather(*start_tasks, return_exceptions=True)
    for (name, worker), res in zip(workers, results, strict=True):
        if isinstance(res, Exception):
            logger.error("worker_start_failed", worker=name, exc_info=res)
            raise res
        started_workers.append(worker)
    return started_workers


async def _stop_workers(started_workers: list[Any]) -> None:
    if not started_workers:
        return
    stop_tasks = [worker.stop() for worker in started_workers]
    results = await asyncio.gather(*stop_tasks, return_exceptions=True)
    for worker, res in zip(started_workers, results, strict=True):
        if isinstance(res, Exception):
            logger.error("worker_stop_failed", worker=worker.__class__.__name__, exc_info=res)


async def main(stop_event: asyncio.Event | None = None) -> None:
    ObservabilityProvider.auto_configure_from_env("unified-worker")
    logger.info("unified_worker_starting")

    worker_modules_env = os.environ.get("WORKER_MODULES", "")
    if not worker_modules_env:
        logger.error("No WORKER_MODULES environment variable provided. Exiting with failure.")
        sys.exit(1)

    module_names = [name.strip() for name in worker_modules_env.split(",") if name.strip()]
    if not module_names:
        logger.error(
            "WORKER_MODULES environment variable is empty after parsing. Exiting with failure."
        )
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

    started_workers = []
    try:
        started_workers = await _start_workers(workers)
        logger.info("all_workers_started_successfully")

        # Wait for termination signal
        await stop_event.wait()

        logger.info("unified_worker_shutting_down")
    finally:
        await _stop_workers(started_workers)

    logger.info("unified_worker_shutdown_complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
