import asyncio
import contextlib
import os
import signal
from typing import Any

import structlog
from database.provider import get_async_engine
from dotenv import load_dotenv
from observability import ObservabilityProvider
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from scheduler_worker.bootstrap.container import Container
from scheduler_worker.config.settings import get_settings

logger = structlog.get_logger(__name__)

# Hold strong references to background tasks to prevent GC (see RUF006)
_background_tasks: set[asyncio.Task[None]] = set()


from seedwork.infra.worker import LaunchableWorker


class SchedulerWorkerModule(LaunchableWorker):
    def __init__(self) -> None:
        self.container: Container | None = None
        self.engine: AsyncEngine | None = None
        self.worker_task: asyncio.Task[None] | None = None
        self.worker: Any | None = None

    async def start(self) -> None:
        logger.info("scheduler_worker_starting")
        # Load .env file from project root
        dotenv_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../../../../../../.env")
        )
        load_dotenv(dotenv_path)

        settings = get_settings()

        self.engine = get_async_engine(settings.async_database_url)
        session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )

        self.container = Container(session_factory=session_factory)
        assert self.container is not None
        self.container.config.from_pydantic(settings)
        self.worker = self.container.worker()
        assert self.worker is not None

        # Start the worker in the background so start() is non-blocking
        self.worker_task = asyncio.create_task(self.worker.start())
        _background_tasks.add(self.worker_task)
        self.worker_task.add_done_callback(_background_tasks.discard)

    async def stop(self) -> None:
        logger.info("Stopping scheduler worker gracefully...")
        try:
            if self.worker:
                await self.worker.stop()
            if self.worker_task:
                # Wait for the background task to complete gracefully
                with contextlib.suppress(asyncio.CancelledError):
                    await self.worker_task
        finally:
            if self.engine:
                await self.engine.dispose()
            logger.info("Database engine disposed. Scheduler worker shutdown complete.")


async def main() -> None:
    ObservabilityProvider.auto_configure_from_env("scheduler-worker")

    module = SchedulerWorkerModule()

    try:
        await module.start()

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
