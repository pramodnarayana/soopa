import asyncio

import structlog
from observability import ObservabilityProvider
from seedwork.infra.worker import run_worker_app, run_worker_app_async

logger = structlog.get_logger(__name__)

# Expose the module for the unified runner
from worker.data.main import EdiOrchestratorWorkerModule


async def main(stop_event: asyncio.Event | None = None) -> None:
    ObservabilityProvider.auto_configure_from_env("edi-orchestrator-worker")
    module = EdiOrchestratorWorkerModule()
    await run_worker_app_async(module, stop_event=stop_event)


if __name__ == "__main__":
    run_worker_app(main)
