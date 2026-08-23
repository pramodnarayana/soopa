import asyncio
import signal

import structlog

from worker.data.main import main as data_main
from worker.provision.main import main as provision_main

logger = structlog.get_logger(__name__)


async def main() -> None:
    logger.info("Starting unified Enterprise EDI Worker (Data + Provisioning)...")

    # Run both the Provisioning and Data worker tasks concurrently
    data_task = asyncio.create_task(data_main())
    provision_task = asyncio.create_task(provision_main())

    def shutdown_handler(*args: object) -> None:
        logger.info("orchestrator_worker_shutdown_signal_received")
        data_task.cancel()
        provision_task.cancel()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, shutdown_handler)
    loop.add_signal_handler(signal.SIGTERM, shutdown_handler)

    try:
        await asyncio.gather(data_task, provision_task)
    finally:
        logger.info("Shutting down top-level worker tasks gracefully...")
        data_task.cancel()
        provision_task.cancel()
        import contextlib

        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(data_task, provision_task, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
