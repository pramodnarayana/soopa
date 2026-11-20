"""Seeds Integration Platform (IP) scheduled maintenance and outbox cron jobs into global_db."""

from __future__ import annotations

import asyncio
import hashlib
import sys
from datetime import UTC, datetime

import structlog
from database.models.scheduling import ScheduledJob
from database.provider import DatabaseProvider
from ip.engine.domain.enums import IpJobName
from scheduler.domain.constants import JobStatus
from seedwork.infra.config import load_settings_safely
from seedwork.infra.config_models import PlatformDatabaseSettings
from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = structlog.get_logger(__name__)

IP_CONTROL_PLANE_JOBS_QUEUE = "ip-control-plane-jobs.fifo"
IP_DATA_PLANE_JOBS_QUEUE = "ip-data-plane-jobs.fifo"


def build_ip_scheduled_jobs(now: datetime | None = None) -> list[dict[str, object]]:
    """Constructs the canonical IP scheduled job definitions."""
    scheduled_time = now or datetime.now(UTC)
    return [
        {
            "name": IpJobName.IP_CONTROL_PLANE_OUTBOX_SWEEPER.value,
            "app_namespace": "ip",
            "payload": {},
            "status": JobStatus.PENDING.value,
            "cron_expression": "* * * * *",
            "target_queue": IP_CONTROL_PLANE_JOBS_QUEUE,
            "retry_count": 0,
            "max_retries": 3,
            "next_run_at": scheduled_time,
        },
        {
            "name": IpJobName.IP_DATA_PLANE_OUTBOX_SWEEPER.value,
            "app_namespace": "ip",
            "payload": {},
            "status": JobStatus.PENDING.value,
            "cron_expression": "* * * * *",
            "target_queue": IP_DATA_PLANE_JOBS_QUEUE,
            "retry_count": 0,
            "max_retries": 3,
            "next_run_at": scheduled_time,
        },
        {
            "name": IpJobName.IP_CONTROL_PLANE_OUTBOX_CLEANUP.value,
            "app_namespace": "ip",
            "payload": {},
            "status": JobStatus.PENDING.value,
            "cron_expression": "0 * * * *",
            "target_queue": IP_CONTROL_PLANE_JOBS_QUEUE,
            "retry_count": 0,
            "max_retries": 3,
            "next_run_at": scheduled_time,
        },
        {
            "name": IpJobName.IP_DATA_PLANE_OUTBOX_CLEANUP.value,
            "app_namespace": "ip",
            "payload": {},
            "status": JobStatus.PENDING.value,
            "cron_expression": "0 * * * *",
            "target_queue": IP_DATA_PLANE_JOBS_QUEUE,
            "retry_count": 0,
            "max_retries": 3,
            "next_run_at": scheduled_time,
        },
        {
            "name": IpJobName.IP_DATA_RETENTION_CLEANUP.value,
            "app_namespace": "ip",
            "payload": {},
            "status": JobStatus.PENDING.value,
            "cron_expression": "30 2 * * *",
            "target_queue": IP_DATA_PLANE_JOBS_QUEUE,
            "retry_count": 0,
            "max_retries": 3,
            "next_run_at": scheduled_time,
        },
    ]


async def seed_ip_jobs() -> None:
    """Idempotently upserts the 5 IP scheduled jobs into scheduling.scheduled_jobs."""
    settings = load_settings_safely(PlatformDatabaseSettings)
    provider = DatabaseProvider.from_url(settings.global_url)
    now = datetime.now(UTC)
    jobs = build_ip_scheduled_jobs(now)

    try:
        async with provider.session() as session:
            logger.info("ip_seed_jobs_starting", job_count=len(jobs))
            for job_data in jobs:
                job_name = str(job_data["name"])
                name_hash = hashlib.sha256(job_name.encode()).hexdigest()[:24]
                job_id = f"job_{name_hash}"
                row = {**job_data, "id": job_id}

                stmt = (
                    pg_insert(ScheduledJob)
                    .values(**row)
                    .on_conflict_do_update(
                        index_elements=[ScheduledJob.id],
                        set_={
                            "name": row["name"],
                            "app_namespace": row["app_namespace"],
                            "cron_expression": row["cron_expression"],
                            "target_queue": row["target_queue"],
                            "next_run_at": now,
                        },
                    )
                )
                await session.execute(stmt)
                logger.info("ip_seed_job_upserted", job_id=job_id, job_name=job_name)

            await session.commit()
            logger.info("ip_seed_jobs_completed")
    except Exception:
        logger.exception("ip_seed_jobs_failed")
        sys.exit(1)
    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(seed_ip_jobs())
