import asyncio
import sys
import uuid
from typing import Any

import structlog

from ucp.adapters.outbound.database.postgres_outbox_repository import PostgresOutboxRepository
from ucp.bootstrap.container import Container
from ucp.ports.outbox_publisher import OutboxPublisherPort

logger = structlog.get_logger(__name__)

# Per-event processing timeout, shorter than the 30s lock lease to allow retries
EVENT_PROCESSING_TIMEOUT_SECONDS = 20


class OutboxRelayWorker:
    def __init__(
        self,
        outbox_repo: PostgresOutboxRepository,
        publisher: OutboxPublisherPort,
    ):
        self.outbox_repo = outbox_repo
        self.publisher = publisher
        self.worker_id = str(uuid.uuid4())

    async def run(self, max_iterations: int | None = None) -> None:
        logger.info("outbox_relay_worker_starting", worker_id=self.worker_id)
        iterations = 0

        async def _run() -> None:
            nonlocal iterations
            while max_iterations is None or iterations < max_iterations:
                try:
                    # Claim events
                    events = await self.outbox_repo.claim_next_events(
                        worker_id=self.worker_id, limit=50, lock_lease_ms=30000
                    )

                    if not events:
                        await asyncio.sleep(2)
                        iterations += 1
                        continue

                    for event in events:
                        try:
                            async with asyncio.timeout(EVENT_PROCESSING_TIMEOUT_SECONDS):
                                await self.process_event(event)
                            await self.outbox_repo.mark_completed(event.id, self.worker_id)
                        except TimeoutError:
                            logger.exception(
                                "outbox_event_processing_timeout",
                                event_id=event.id,
                                timeout_seconds=EVENT_PROCESSING_TIMEOUT_SECONDS,
                            )
                            await self.outbox_repo.mark_failed(
                                event.id,
                                self.worker_id,
                                f"Timeout after {EVENT_PROCESSING_TIMEOUT_SECONDS}s",
                            )
                        except Exception as e:
                            logger.exception("outbox_event_processing_failed", event_id=event.id)
                            await self.outbox_repo.mark_failed(event.id, self.worker_id, str(e))
                except Exception:
                    logger.exception("outbox_relay_worker_loop_error")
                    await asyncio.sleep(5)

                iterations += 1

        if hasattr(self.publisher, "__aenter__"):
            async with self.publisher:
                await _run()
        else:
            await _run()

    async def process_event(self, event: Any) -> None:
        logger.info(
            "processing_outbox_event_in_relay", event_type=event.event_type, event_id=event.id
        )
        await self.publisher.publish(event)


async def main() -> None:
    container = Container()
    container.wire(modules=[sys.modules[__name__]])

    worker = OutboxRelayWorker(
        outbox_repo=container.outbox_repo(),
        publisher=container.outbox_publisher(),
    )

    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
