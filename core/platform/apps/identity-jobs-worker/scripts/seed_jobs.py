import asyncio
import hashlib
import sys
from datetime import UTC, datetime

import structlog
from database.models.scheduling import ScheduledJob
from database.provider import DatabaseProvider
from identity.domain.constants import IdentityJobName
from scheduler.domain.constants import JobStatus
from sqlalchemy.dialects.postgresql import insert as pg_insert

from identity_jobs_worker.config.settings import get_settings

logger = structlog.get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    provider = DatabaseProvider.from_url(settings.database_url)
    queue_url = settings.sqs_identity_jobs_queue_url
    target_queue = queue_url.rstrip("/").split("/")[-1] if queue_url else "identity-jobs.fifo"

    jobs: list[dict[str, object]] = [
        {
            "name": IdentityJobName.IDENTITY_OUTBOX_SWEEPER.value,
            "app_namespace": "identity",
            "payload": {},
            "status": JobStatus.PENDING.value,
            "cron_expression": "* * * * *",
            "target_queue": target_queue,
            "retry_count": 0,
            "max_retries": 3,
            "next_run_at": datetime.now(UTC),
        },
        {
            "name": IdentityJobName.IDENTITY_OUTBOX_CLEANUP.value,
            "app_namespace": "identity",
            "payload": {},
            "status": JobStatus.PENDING.value,
            "cron_expression": "* * * * *",
            "target_queue": target_queue,
            "retry_count": 0,
            "max_retries": 3,
            "next_run_at": datetime.now(UTC),
        },
    ]

    try:
        async with provider.session() as session:
            logger.info("identity_seed_jobs_starting", job_count=len(jobs))
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
                            "next_run_at": datetime.now(UTC),
                        },
                    )
                )
                await session.execute(stmt)
                logger.info("identity_seed_job_upserted", job_id=job_id, job_name=job_name)
            await session.commit()
            logger.info("identity_seed_jobs_completed")
    except Exception:
        logger.exception("identity_seed_jobs_failed")
        sys.exit(1)
    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
