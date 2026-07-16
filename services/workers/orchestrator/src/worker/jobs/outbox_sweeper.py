import asyncio
import datetime
import json
import logging
import os
from typing import Any

import aioboto3  # type: ignore[import-untyped]
from database.connection import DatabaseRouter
from database.models.control_plane import DatabaseShard
from database.models.data_plane import DataPlaneOutbox
from domain.events import MessageQueueName, PipelineEventType
from scheduler.domain.models import Job
from scheduler.ports.handler import JobHandlerPort
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Maps each pipeline event type to its target SQS queue
_EVENT_QUEUE_MAP: dict[str, str] = {
    PipelineEventType.TRANSFORM_EVENT: MessageQueueName.TRANSFORM_ORCHESTRATION_QUEUE,
    PipelineEventType.COMPUTE_TRANSFORM_EVENT: MessageQueueName.TRANSFORM_COMPUTE_QUEUE,
    PipelineEventType.TRANSFORM_COMPLETED: MessageQueueName.TRANSFORM_ORCHESTRATION_QUEUE,
    PipelineEventType.DELIVER_EVENT: MessageQueueName.DELIVER_QUEUE,
    PipelineEventType.DELIVERY_COMPLETED: MessageQueueName.TRANSFORM_ORCHESTRATION_QUEUE,
}

# Maximum number of events to sweep per run to bound wall-clock time
_BATCH_SIZE = 100
_CONCURRENCY_LIMIT = 5


class DataPlaneOutboxSweeperJobHandler(JobHandlerPort):
    def __init__(self, db_router: DatabaseRouter) -> None:
        self.db_router = db_router
        self._endpoint_url = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
        self._region = "us-east-1"
        self._session = aioboto3.Session()

    async def execute(self, job: Job) -> datetime.datetime | None:
        """
        Sweeps the data-plane (tenant shard) outbox for PENDING pipeline events
        and forwards each one to the appropriate SQS queue using concurrent batching.
        """
        logger.info(f"[DataPlaneOutboxSweeper] Running sweep for job {job.id}")

        total_processed = 0
        sem = asyncio.Semaphore(_CONCURRENCY_LIMIT)

        # We share one SQS client pool across all shards
        async with self._session.client(
            "sqs", endpoint_url=self._endpoint_url, region_name=self._region
        ) as sqs:
            queue_url_cache: dict[str, str] = {}

            async for global_session in self.db_router.get_global_session():
                res = await global_session.execute(select(DatabaseShard))
                shards = res.scalars().all()

                async def _bounded_sweep(shard_name: str, shard_dsn: str) -> int:
                    async with sem:
                        return await self._sweep_shard(shard_name, shard_dsn, sqs, queue_url_cache)

                results = await asyncio.gather(
                    *[_bounded_sweep(shard.name, shard.dsn) for shard in shards]
                )
                total_processed += sum(results)

        logger.info(
            f"[DataPlaneOutboxSweeper] Sweep complete. Total events forwarded: {total_processed}"
        )

        interval_seconds = job.payload.get("interval_seconds", 60) if job.payload else 60
        return datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=interval_seconds)

    async def _sweep_shard(
        self, shard_name: str, shard_dsn: str, sqs: Any, queue_url_cache: dict[str, str]
    ) -> int:
        """Sweep a single tenant shard outbox, dispatching via SQS batching."""
        processed = 0

        engine = await self.db_router.get_engine(shard_name, shard_dsn)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            stmt = (
                select(DataPlaneOutbox)
                .where(
                    DataPlaneOutbox.status == "PENDING",
                    DataPlaneOutbox.event_type.in_(list(PipelineEventType)),
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
                queue_name = _EVENT_QUEUE_MAP.get(event.event_type)
                if not queue_name:
                    logger.warning(
                        f"[DataPlaneOutboxSweeper] Unknown event_type={event.event_type!r} "
                        f"for event id={event.id}. Marking FAILED."
                    )
                    event.status = "FAILED"
                    continue
                batches_by_queue.setdefault(queue_name, []).append(event)

            for queue_name, queue_events in batches_by_queue.items():
                if queue_name not in queue_url_cache:
                    try:
                        resp = await sqs.get_queue_url(QueueName=queue_name)
                        queue_url_cache[queue_name] = resp["QueueUrl"]
                    except Exception:
                        logger.exception(
                            f"[DataPlaneOutboxSweeper] Failed to get queue url for {queue_name}"
                        )
                        continue

                queue_url = queue_url_cache[queue_name]

                # SQS allows max 10 messages per batch
                for i in range(0, len(queue_events), 10):
                    batch = queue_events[i : i + 10]
                    entries = []
                    for event in batch:
                        entries.append(
                            {
                                "Id": str(event.id),  # SQS entry ID must be string
                                "MessageBody": json.dumps(
                                    {
                                        "idempotency_key": str(event.idempotency_key),
                                        "event_type": event.event_type,
                                        "payload": event.payload,
                                        "tenant_id": event.tenant_id,
                                    }
                                ),
                            }
                        )

                    try:
                        resp = await sqs.send_message_batch(QueueUrl=queue_url, Entries=entries)
                        # Process successful IDs
                        for success in resp.get("Successful", []):
                            event_id = success["Id"]
                            # Find the event object
                            for ev in batch:
                                if str(ev.id) == event_id:
                                    ev.status = "PROCESSED"
                                    processed += 1
                                    break

                        # Log failures if any
                        for failed in resp.get("Failed", []):
                            logger.error(
                                f"[DataPlaneOutboxSweeper] Failed to forward event id={failed['Id']}: "
                                f"{failed['Message']}"
                            )
                    except Exception:
                        logger.exception(
                            f"[DataPlaneOutboxSweeper] Failed to send batch to {queue_name}"
                        )

            # Commit the session. Only events marked PROCESSED/FAILED above will be updated.
            # The ones that failed to send via SQS will simply remain PENDING in the DB (no modification made)
            # because we did not change their status.
            await session.commit()

        return processed
