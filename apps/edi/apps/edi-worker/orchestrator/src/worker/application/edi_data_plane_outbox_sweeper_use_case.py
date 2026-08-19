import asyncio
import datetime

import structlog
from database.connection import DatabaseRouter
from database.models.data_plane import DataPlaneOutbox
from domain.events import PIPELINE_EVENT_ROUTING_MAP
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.infrastructure import DatabaseShard

from worker.ports.message_publisher import MessagePublisherPort, PublishMessageEnvelope

logger = structlog.get_logger(__name__)

_BATCH_SIZE = 100
_CONCURRENCY_LIMIT = 5


class EdiDataPlaneOutboxSweeperUseCase:
    def __init__(self, db_router: DatabaseRouter, message_publisher: MessagePublisherPort) -> None:
        self.db_router = db_router
        self.message_publisher = message_publisher

    async def execute(self) -> int:
        """
        Sweeps the data-plane (tenant shard) outbox for PENDING pipeline events
        and forwards each one to the appropriate SQS queue using concurrent batching.
        Returns the total number of processed events.
        """
        logger.info("[EdiDataPlaneOutboxSweeperUseCase] Running sweep")

        total_processed = 0
        sem = asyncio.Semaphore(_CONCURRENCY_LIMIT)

        async with self.message_publisher.connect():
            async for global_session in self.db_router.get_global_session():
                res = await global_session.execute(select(DatabaseShard))
                shards = res.scalars().all()

            async def _bounded_sweep(shard_name: str, shard_dsn: str) -> int:
                async with sem:
                    try:
                        return await self._sweep_shard(shard_name, shard_dsn)
                    except Exception:
                        logger.exception("sweep_shard_failed", shard_name=shard_name)
                        return 0

            results = await asyncio.gather(
                *[_bounded_sweep(shard.name, shard.dsn) for shard in shards]
            )
            total_processed += sum(results)

        logger.info(
            "[EdiDataPlaneOutboxSweeperUseCase] Sweep complete. Total events forwarded: {total_processed}",
            total_processed=total_processed,
        )

        return total_processed

    async def _sweep_shard(self, shard_name: str, shard_dsn: str) -> int:
        """Sweep a single tenant shard outbox, dispatching via SQS batching."""
        processed = 0

        engine = await self.db_router.get_engine(shard_name, shard_dsn)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            # Only sweep events older than 5 minutes to avoid racing with Debezium CDC
            five_mins_ago = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=5)
            stmt = (
                select(DataPlaneOutbox)
                .where(
                    DataPlaneOutbox.status == "PENDING",
                    DataPlaneOutbox.event_type.in_(list(PIPELINE_EVENT_ROUTING_MAP.keys())),
                    DataPlaneOutbox.created_at < five_mins_ago,
                )
                .limit(_BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
            result = await session.execute(stmt)
            events = result.scalars().all()

            if not events:
                logger.debug(
                    "[EdiDataPlaneOutboxSweeperUseCase] No pending events on shard={shard_name}",
                    shard_name=shard_name,
                )
                return 0

            # Group events by target queue to utilize SQS send_message_batch
            batches_by_queue: dict[str, list[DataPlaneOutbox]] = {}
            for event in events:
                queue_name = PIPELINE_EVENT_ROUTING_MAP.get(event.event_type)
                if not queue_name:
                    logger.warning(
                        "[EdiDataPlaneOutboxSweeperUseCase] Unknown event_type={event.event_type!r} "
                        "for event id={event.id}. Marking FAILED."
                    )
                    event.status = "FAILED"
                    continue
                batches_by_queue.setdefault(queue_name, []).append(event)

            for queue_name, queue_events in batches_by_queue.items():
                messages = []
                for event in queue_events:
                    messages.append(
                        PublishMessageEnvelope(
                            message_id=str(event.id),
                            event_type=event.event_type,
                            event={
                                "payload": event.payload,
                                "tenant_id": event.tenant_id,
                            },
                            idempotency_key=str(event.idempotency_key)
                            if event.idempotency_key
                            else None,
                        )
                    )

                successful_ids = await self.message_publisher.publish_batch(queue_name, messages)

                for event in queue_events:
                    if str(event.id) in successful_ids:
                        event.status = "PROCESSED"
                        processed += 1
                    else:
                        logger.error(
                            "[EdiDataPlaneOutboxSweeperUseCase] Failed to forward event id={event.id} to {queue_name}",
                            event_id=event.id,
                            queue_name=queue_name,
                        )

            await session.commit()

        return processed
