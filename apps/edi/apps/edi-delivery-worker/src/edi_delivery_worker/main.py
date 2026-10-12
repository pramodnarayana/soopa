import argparse
import asyncio

import structlog
from observability import ObservabilityProvider
from seedwork.infra.worker import run_worker_app, run_worker_app_async

logger = structlog.get_logger(__name__)

from edi_delivery_worker.data.main import EdiDeliveryWorkerModule


async def main(stop_event: asyncio.Event | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the EDI delivery worker")
    parser.add_argument("--dlq", action="store_true", help="Run as DLQ consumer")
    args, _ = parser.parse_known_args()

    ObservabilityProvider.auto_configure_from_env(
        "edi-delivery-dlq-worker" if args.dlq else "edi-delivery-worker"
    )
    logger.info("delivery_worker_starting", is_dlq=args.dlq)

    module = EdiDeliveryWorkerModule(is_dlq=args.dlq)
    await run_worker_app_async(module, stop_event=stop_event)


if __name__ == "__main__":
    run_worker_app(main)
