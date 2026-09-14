import asyncio
import os
import signal

import structlog
from database.provider import get_async_engine
from dotenv import load_dotenv
from observability import ObservabilityProvider
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scheduler_worker.bootstrap.container import Container
from scheduler_worker.config.settings import get_settings

logger = structlog.get_logger(__name__)

# Hold strong references to background tasks to prevent GC (see RUF006)
_background_tasks: set[asyncio.Task[None]] = set()


async def main() -> None:
    # Load .env file from project root
    dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../../.env"))
    load_dotenv(dotenv_path)
    ObservabilityProvider.auto_configure_from_env("scheduler-worker")

    settings = get_settings()

    logger.info("scheduler_worker_starting")

    engine = get_async_engine(settings.async_database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    container = Container(session_factory=session_factory)
    container.config.from_pydantic(settings)
    worker = container.worker()

    loop = asyncio.get_running_loop()

    # Graceful shutdown handler
    def handle_sigint() -> None:
        logger.info("Received SIGINT, stopping worker gracefully...")
        task = asyncio.create_task(worker.stop())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    def handle_sigterm() -> None:
        logger.info("Received SIGTERM, stopping worker gracefully...")
        task = asyncio.create_task(worker.stop())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_sigint if sig == signal.SIGINT else handle_sigterm)

    try:
        await worker.start()
    finally:
        await engine.dispose()
        logger.info("Database engine disposed. Exiting.")


if __name__ == "__main__":
    asyncio.run(main())
