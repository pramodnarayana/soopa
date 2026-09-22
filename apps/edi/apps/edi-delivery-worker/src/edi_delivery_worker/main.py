import asyncio
import signal

import structlog
from observability import ObservabilityProvider

logger = structlog.get_logger(__name__)


from edi_delivery_worker.data.main import EdiDeliveryWorkerModule


async def main() -> None:
    ObservabilityProvider.auto_configure_from_env("edi-delivery-worker")
    logger.info("delivery_worker_starting")

    module = EdiDeliveryWorkerModule()

    try:
        await module.start()

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        def shutdown_handler(*args: object) -> None:
            logger.info("delivery_worker_shutdown_signal_received")
            stop_event.set()

        loop.add_signal_handler(signal.SIGINT, shutdown_handler)
        loop.add_signal_handler(signal.SIGTERM, shutdown_handler)

        await stop_event.wait()
    finally:
        logger.info("delivery_worker_stopped")
        await module.stop()


if __name__ == "__main__":
    asyncio.run(main())
