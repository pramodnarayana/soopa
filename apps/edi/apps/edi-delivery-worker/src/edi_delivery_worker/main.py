import argparse
import asyncio

import structlog
from observability import ObservabilityProvider
from seedwork.infra.worker import LaunchableWorker, run_worker_app, run_worker_app_async

from edi_delivery_worker.data.main import (
    EdiDeliveryDlqWorkerModule,
    EdiDeliveryWorkerModule,
)

logger = structlog.get_logger(__name__)


async def main(stop_event: asyncio.Event | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the EDI delivery worker")
    parser.add_argument("--dlq", action="store_true", help="Run as DLQ consumer")
    args, _ = parser.parse_known_args()

    if args.dlq:
        ObservabilityProvider.auto_configure_from_env("edi-delivery-dlq-worker")
        module: LaunchableWorker = EdiDeliveryDlqWorkerModule()
    else:
        ObservabilityProvider.auto_configure_from_env("edi-delivery-worker")
        module = EdiDeliveryWorkerModule()

    logger.info("delivery_worker_starting", mode="dlq" if args.dlq else "primary")
    await run_worker_app_async(module, stop_event=stop_event)


if __name__ == "__main__":
    run_worker_app(main)
