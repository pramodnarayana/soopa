import asyncio
import logging
import os
import signal
import sys

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from scheduler_engine.worker import SchedulerWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Hold strong references to background tasks to prevent GC (see RUF006)
_background_tasks: set[asyncio.Task[None]] = set()


async def main() -> None:
    # Load .env file from project root
    dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../../.env"))
    load_dotenv(dotenv_path)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL is not set")
        sys.exit(1)

    # Convert to asyncpg
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    import punq

    from .adapters.outbound.dummy_job_dispatcher import DummyJobDispatcher
    from .adapters.outbound.postgres_job_repository import SqlAlchemyJobRepository
    from .ports.job_dispatcher import JobDispatcherPort
    from .ports.job_repository import JobRepositoryPort

    container = punq.Container()
    container.register(async_sessionmaker[AsyncSession], instance=session_factory)
    container.register(JobRepositoryPort, SqlAlchemyJobRepository)
    container.register(JobDispatcherPort, DummyJobDispatcher)

    worker = SchedulerWorker(
        repository=container.resolve(JobRepositoryPort),
        dispatcher=container.resolve(JobDispatcherPort),
        poll_interval_seconds=int(os.environ.get("SCHEDULER_POLL_INTERVAL_SECONDS", "5")),
        max_concurrent_jobs=int(os.environ.get("SCHEDULER_MAX_CONCURRENT_JOBS", "10")),
    )

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
