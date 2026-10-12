import asyncio
import contextlib
import inspect
import signal
import sys
from collections.abc import Callable, Coroutine
from typing import Protocol, cast, runtime_checkable

import structlog
from pydantic import ValidationError

logger = structlog.get_logger(__name__)


@runtime_checkable
class LaunchableWorker(Protocol):
    """
    Enterprise Standard:
    Every background worker module must implement this exact protocol.
    The unified runner will blindly call `await start()` and `await stop()`.
    """

    async def start(self) -> None:
        """Start the background worker tasks."""
        ...

    async def stop(self) -> None:
        """Gracefully stop the background worker tasks."""
        ...

    def get_background_tasks(self) -> list[asyncio.Task[object]]:
        """
        Return a list of critical background tasks that should crash the worker
        if they terminate unexpectedly.
        """
        return []


async def run_worker_app_async(
    module: LaunchableWorker,
    stop_event: asyncio.Event | None = None,
) -> None:
    """
    Centralized worker application lifecycle runner.
    Handles startup, graceful shutdown via SIGTERM/SIGINT, and monitoring
    of background tasks to ensure the container crashes if a critical task fails.
    """
    tasks_to_wait: list[asyncio.Task[object]] = []
    try:
        await module.start()

        if stop_event is None:
            stop_event = asyncio.Event()
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
                    loop.add_signal_handler(sig, stop_event.set)

        tasks_to_wait.append(asyncio.create_task(stop_event.wait()))
        tasks_to_wait.extend(module.get_background_tasks())

        done, _pending = await asyncio.wait(tasks_to_wait, return_when=asyncio.FIRST_COMPLETED)

        # If any critical task died (other than the stop_event), propagate the exception
        for task in done:
            if task is not tasks_to_wait[0] and task.exception():
                exc = task.exception()
                logger.error("worker_background_task_failed", exc_info=exc)
                if exc:
                    raise exc
    finally:
        for task in tasks_to_wait:
            if not task.done():
                task.cancel()
        await module.stop()


def run_worker_app(
    target: Callable[[], Coroutine[object, object, None]] | Callable[[], LaunchableWorker],
) -> None:
    """
    Synchronous entrypoint to bootstrap a LaunchableWorker or async main coroutine.
    Handles standard application lifecycle and formatting of startup errors
    like Pydantic configuration validation.
    """
    try:
        res = target()
        if inspect.iscoroutine(res):
            asyncio.run(res)
        else:
            module = cast(LaunchableWorker, res)
            asyncio.run(run_worker_app_async(module))
    except KeyboardInterrupt:
        logger.info("worker_stopped_by_signal")
        sys.exit(0)
    except ValidationError as e:
        all_errors = e.errors()

        missing_fields = [
            f"{'.'.join(str(loc_item) for loc_item in err.get('loc', []))} ({err.get('msg', '')})"
            for err in all_errors
            if err.get("type") in ("missing", "value_error.missing")
        ]
        invalid_fields = [
            f"{'.'.join(str(loc_item) for loc_item in err.get('loc', []))} ({err.get('msg', '')})"
            for err in all_errors
            if err.get("type") not in ("missing", "value_error.missing")
        ]

        if missing_fields:
            logger.exception(
                "worker_startup_configuration_error",
                reason="One or more required environment variables are missing from your .env file.",
                missing_fields=missing_fields,
                remedy="Please check .env.example and ensure all required variables are set.",
            )
        if invalid_fields:
            logger.exception(
                "worker_startup_configuration_error",
                reason="One or more environment variables have invalid configured values.",
                invalid_fields=invalid_fields,
            )
        raise
    except Exception:
        logger.exception("worker_startup_failed", reason="Startup initialization error")
        raise
