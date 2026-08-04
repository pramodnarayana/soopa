import asyncio
import datetime
import logging

from database.connection import DatabaseRouter
from ucp_models.infrastructure import DatabaseShard
from database.models.data_plane import DataPlaneOutbox
from domain.events import PIPELINE_EVENT_ROUTING_MAP, PipelineEventType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from worker.core.scheduler.handler import JobHandlerPort
from worker.core.scheduler.models import Job
from worker.ports.message_publisher import MessagePublisherPort

logger = logging.getLogger(__name__)

_BATCH_SIZE = 100
_CONCURRENCY_LIMIT = 5


class DataPlaneOutboxSweeperJobHandler(JobHandlerPort):
    def __init__(self, db_router: DatabaseRouter, message_publisher: MessagePublisherPort) -> None:
        self.db_router = db_router
        self.message_publisher = message_publisher

    async def execute(self, job: Job) -> datetime.datetime | None:
        """
        Sweeps the data-plane (tenant shard) outbox for PENDING pipeline events
        and forwards each one to the appropriate SQS queue using concurrent batching.
        """
        logger.info(f"[DataPlaneOutboxSweeper] Running sweep for job {job.id}")

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
                    except Exception as e:
                        logger.error(
                            f"[DataPlaneOutboxSweeper] Failed sweeping shard {shard_name}: {e}"
                        )
                        return 0

            results = await asyncio.gather(
                *[_bounded_sweep(shard.name, shard.dsn) for shard in shards]
            )
            total_processed += sum(results)

        logger.info(
            f"[DataPlaneOutboxSweeper] Sweep complete. Total events forwarded: {total_processed}"
        )

        interval_seconds = (
            job.interval_seconds if job.interval_seconds and job.interval_seconds > 0 else 60
        )
        return datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=interval_seconds)

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
                    DataPlaneOutbox.event_type.in_(list(PipelineEventType)),
                    DataPlaneOutbox.created_at < five_mins_ago,
                )
                .limit(_BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
            result = await session.execute(stmt)
            events = result.scalars().all()

            if not events:
                logger.debug(f"[DataPlaneOutboxSweeper] No pending events on shard={shard_name}")
                return 0

            # Group events by target queue to utilize SQS send_message_batch
            batches_by_queue: dict[str, list[DataPlaneOutbox]] = {}
            for event in events:
                queue_name = PIPELINE_EVENT_ROUTING_MAP.get(event.event_type)
                if not queue_name:
                    logger.warning(
                        f"[DataPlaneOutboxSweeper] Unknown event_type={event.event_type!r} "
                        f"for event id={event.id}. Marking FAILED."
                    )
                    event.status = "FAILED"
                    continue
                batches_by_queue.setdefault(queue_name, []).append(event)

            for queue_name, queue_events in batches_by_queue.items():
                messages = []
                for event in queue_events:
                    messages.append(
                        {
                            "Id": str(event.id),
                            "MessageBody": {
                                "idempotency_key": str(event.idempotency_key),
                                "event_type": event.event_type,
                                "payload": event.payload,
                                "tenant_id": event.tenant_id,
                            },
                        }
                    )

                successful_ids = await self.message_publisher.publish_batch(queue_name, messages)

                for event in queue_events:
                    if str(event.id) in successful_ids:
                        event.status = "PROCESSED"
                        processed += 1
                    else:
                        logger.error(
                            f"[DataPlaneOutboxSweeper] Failed to forward event id={event.id} to {queue_name}"
                        )

            # Commit the session. Only events marked PROCESSED/FAILED above will be updated.
            # The ones that failed to send via SQS will simply remain PENDING in the DB (no modification made)
            # because we did not change their status.
            await session.commit()

        return processed
