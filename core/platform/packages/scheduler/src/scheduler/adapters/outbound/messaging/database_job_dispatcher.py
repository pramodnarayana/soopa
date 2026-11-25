"""Cloud-agnostic DatabaseQueuePort & in-process job dispatcher implementing JobDispatcherPort."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from enum import StrEnum

import structlog
from pubsub.domain.enums import normalize_database_queue_name
from pubsub.ports.database_queue_port import DatabaseQueuePort
from seedwork.events import EventEnvelope, EventProcessingLane
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id

from scheduler.domain.scheduled_job import ScheduledJob
from scheduler.ports.outbound.job_dispatcher_port import JobDispatcherPort

logger = structlog.get_logger(__name__)

JobCallback = Callable[[ScheduledJob], Awaitable[None]]


class SchedulerEventSource(StrEnum):
    """Canonical event source identifiers emitted by the platform scheduler."""

    PLATFORM_SCHEDULER = "platform.scheduler"


class DatabaseJobDispatcher(JobDispatcherPort):
    """Cloud-agnostic JobDispatcherPort delegating durable queue writes to `DatabaseQueuePort`.

    Supports two zero-broker execution strategies:
    1. Direct in-process callback execution (e.g., `platform_queue_cleanup`).
    2. Durable PostgreSQL queue insertion via injected `DatabaseQueuePort` (`pubsub.platform_queue_messages`),
       consumed by worker containers via `DirectOutboxConsumerManager` (`FOR UPDATE SKIP LOCKED`).

    Depends strictly on the abstract `DatabaseQueuePort` protocol (zero concrete adapter coupling
    and zero in-memory history accumulation).
    """

    def __init__(
        self,
        database_queue: DatabaseQueuePort | None = None,
        queue_url_map: Mapping[str, str] | None = None,
        handlers: Mapping[str, JobCallback] | None = None,
    ) -> None:
        self._database_queue = database_queue
        self._queue_url_map: dict[str, str] = dict(queue_url_map or {})
        self._handlers: dict[str, JobCallback] = dict(handlers or {})

    def register_handler(self, job_name: str, handler: JobCallback) -> None:
        """Registers an in-process async handler for a scheduled job name."""
        self._handlers[job_name] = handler

    async def dispatch(self, job: ScheduledJob) -> None:
        handler = self._handlers.get(job.name)
        if handler is not None:
            await handler(job)
            logger.info(
                "database_job_dispatcher_executed_in_process",
                job_id=job.id,
                job_name=job.name,
            )
            return

        if not job.target_queue:
            logger.error(
                "database_job_dispatcher_missing_target_queue",
                job_id=job.id,
                job_name=job.name,
            )
            raise ValueError(f"No in-process handler or target_queue defined for job {job.name}")

        if self._database_queue is None:
            raise ValueError(
                f"Cannot dispatch scheduled job '{job.name}' ({job.id}): "
                "neither an in-process handler nor a DatabaseQueuePort is configured."
            )

        target_uri = self._queue_url_map.get(job.target_queue, job.target_queue)
        queue_name = normalize_database_queue_name(target_uri)
        now = datetime.now(UTC)
        minute_bucket = now.strftime("%Y%m%d%H%M")
        idempotency_key = f"sched_{job.name}_{job.id}_{minute_bucket}"
        envelope = EventEnvelope(
            id=generate_id(SystemIdPrefix.GENERIC),
            source=SchedulerEventSource.PLATFORM_SCHEDULER.value,
            event_type=f"job.{job.name}.scheduled",
            tenant_id=job.app_namespace or "platform",
            idempotency_key=idempotency_key,
            trace_id=generate_id(SystemIdPrefix.TRACE),
            lane=EventProcessingLane.REALTIME,
            payload={
                "job_id": job.id,
                "job_name": job.name,
                "payload": dict(job.payload),
            },
        )
        await self._database_queue.enqueue(queue_name, envelope)
        logger.info(
            "database_job_dispatcher_enqueued",
            job_id=job.id,
            job_name=job.name,
            queue_name=queue_name,
        )
