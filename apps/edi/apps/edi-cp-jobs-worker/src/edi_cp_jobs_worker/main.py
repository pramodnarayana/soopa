import asyncio
import signal
import typing
from typing import Any

import structlog
from observability import ObservabilityProvider

from edi_cp_jobs_worker.bootstrap.container import WorkerContainer

logger = structlog.get_logger(__name__)


async def main() -> None:
    ObservabilityProvider.auto_configure_from_env("edi-cp-jobs-worker")
    logger.info("edi_cp_jobs_worker.starting")
    container = WorkerContainer()
    container.wire()

    try:
        await container.start()

        stop_event = asyncio.Event()

        def shutdown_handler(*args: object) -> None:
            logger.info("edi_cp_jobs_worker_shutdown_signal_received")
            stop_event.set()

        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, shutdown_handler)
        loop.add_signal_handler(signal.SIGTERM, shutdown_handler)

        tasks: list[asyncio.Task[Any]] = [asyncio.create_task(stop_event.wait())]
        if container.cp_manager and getattr(container.cp_manager, "_task", None):
            tasks.append(typing.cast(asyncio.Task[Any], container.cp_manager._task))
        if container.cp_outbox_relay and getattr(container.cp_outbox_relay, "_task", None):
            tasks.append(typing.cast(asyncio.Task[Any], container.cp_outbox_relay._task))

        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        for task in done:
            if task is not tasks[0] and task.exception():
                exc = task.exception()
                logger.error("edi_cp_jobs_worker_task_failed", exc_info=exc)
                if exc:
                    raise exc

    except asyncio.CancelledError:
        logger.info("edi_cp_jobs_worker_cancelled")
    except Exception:
        logger.exception("edi_cp_jobs_worker_failed")
        raise
    finally:
        logger.info("edi_cp_jobs_worker_shutting_down")
        await container.dispose()
        logger.info("edi_cp_jobs_worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
