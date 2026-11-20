import asyncio
import hashlib
import sys
from datetime import UTC, datetime

import structlog
from database.models.scheduling import ScheduledJob
from database.provider import DatabaseProvider
from edi.domain.enums import EdiJobName
from scheduler.domain.constants import JobStatus
from seedwork.infra.config import load_settings_safely
from seedwork.infra.config_models import PlatformDatabaseSettings
from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = structlog.get_logger(__name__)


async def main() -> None:
    settings = load_settings_safely(PlatformDatabaseSettings)
    provider = DatabaseProvider.from_url(settings.global_url)

    # Note: Using cron `* * * * *` means every minute.
    jobs: list[dict[str, object]] = [
        {
            "name": EdiJobName.EDI_CONTROL_PLANE_OUTBOX_SWEEPER.value,
            "app_namespace": "edi",
            "payload": {},
            "status": JobStatus.PENDING.value,
            "cron_expression": "* * * * *",
            "target_queue": "edi-control-plane-jobs.fifo",
            "retry_count": 0,
            "max_retries": 3,
            "next_run_at": datetime.now(UTC),
        },
        {
            "name": EdiJobName.EDI_DATA_PLANE_OUTBOX_SWEEPER.value,
            "app_namespace": "edi",
            "payload": {},
            "status": JobStatus.PENDING.value,
            "cron_expression": "* * * * *",
            "target_queue": "edi-data-plane-jobs.fifo",
            "retry_count": 0,
            "max_retries": 3,
            "next_run_at": datetime.now(UTC),
        },
        {
            "name": EdiJobName.EDI_CONTROL_PLANE_OUTBOX_CLEANUP.value,
            "app_namespace": "edi",
            "payload": {},
            "status": JobStatus.PENDING.value,
            "cron_expression": "* * * * *",  # Changed from 0 * * * * for development visibility
            "target_queue": "edi-control-plane-jobs.fifo",
            "retry_count": 0,
            "max_retries": 3,
            "next_run_at": datetime.now(UTC),
        },
        {
            "name": EdiJobName.EDI_DATA_PLANE_OUTBOX_CLEANUP.value,
            "app_namespace": "edi",
            "payload": {},
            "status": JobStatus.PENDING.value,
            "cron_expression": "* * * * *",  # Changed from 0 * * * * for development visibility
            "target_queue": "edi-data-plane-jobs.fifo",
            "retry_count": 0,
            "max_retries": 3,
            "next_run_at": datetime.now(UTC),
        },
        {
            "name": EdiJobName.EDI_DATA_RETENTION_CLEANUP.value,
            "app_namespace": "edi",
            "payload": {},
            "status": JobStatus.PENDING.value,
            "cron_expression": "0 2 * * *",  # Nightly at 2am
            "target_queue": "edi-data-plane-jobs.fifo",
            "retry_count": 0,
            "max_retries": 3,
            "next_run_at": datetime.now(UTC),
        },
    ]

    try:
        async with provider.session() as session:
            logger.info("edi_seed_jobs_starting", job_count=len(jobs))

            for job_data in jobs:
                # Generate a deterministic, cryptographically-secure-looking ID based on the job name
                # to satisfy the "job_{bytes}" enterprise ID generation standard while keeping the seed idempotent.
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
                            "next_run_at": datetime.now(UTC),
                        },
                    )
                )
                await session.execute(stmt)
                logger.info("edi_seed_job_upserted", job_id=job_id, job_name=job_name)

            await session.commit()
            logger.info("edi_seed_jobs_completed")
    except Exception:
        logger.exception("edi_seed_jobs_failed")
        sys.exit(1)
    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
