import asyncio
import signal

import structlog

from worker.data.main import main as data_main

logger = structlog.get_logger(__name__)


async def main() -> None:
    logger.info("orchestrator_worker_starting")

    data_task = asyncio.create_task(data_main())

    def shutdown_handler(*args: object) -> None:
        logger.info("orchestrator_worker_shutdown_signal_received")
        data_task.cancel()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, shutdown_handler)
    loop.add_signal_handler(signal.SIGTERM, shutdown_handler)

    try:
        await data_task
    except asyncio.CancelledError:
        logger.info("orchestrator_worker_cancelled")
    finally:
        logger.info("orchestrator_worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
