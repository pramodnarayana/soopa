import asyncio
import hashlib
import os
import sys
from datetime import UTC, datetime

import structlog
from database.models.scheduling import ScheduledJob
from database.provider import DatabaseProvider
from database.utils import normalize_to_asyncpg
from scheduler.domain.constants import JobStatus
from seedwork.infra.config import load_repo_env
from sqlalchemy.dialects.postgresql import insert as pg_insert
from ucp.domain.constants import UcpCleanupJobName, UcpJobName

load_repo_env(override=False)
logger = structlog.get_logger(__name__)


async def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        logger.error("ucp_seed_jobs_missing_database_url")
        sys.exit(1)

    provider = DatabaseProvider.from_url(normalize_to_asyncpg(database_url))

    jobs: list[dict[str, object]] = [
        {
            "name": UcpJobName.UCP_OUTBOX_SWEEPER.value,
            "payload": {},
            "status": JobStatus.PENDING.value,
            "cron_expression": "* * * * *",
            "target_queue": "ucp-jobs.fifo",
            "retry_count": 0,
            "max_retries": 3,
            "next_run_at": datetime.now(UTC),
        },
        {
            "name": UcpCleanupJobName.UCP_OUTBOX_CLEANUP.value,
            "payload": {},
            "status": JobStatus.PENDING.value,
            "cron_expression": "* * * * *",
            "target_queue": "ucp-jobs.fifo",
            "retry_count": 0,
            "max_retries": 3,
            "next_run_at": datetime.now(UTC),
        },
        {
            "name": UcpCleanupJobName.UCP_IDEMPOTENCY_CLEANUP.value,
            "payload": {},
            "status": JobStatus.PENDING.value,
            "cron_expression": "* * * * *",
            "target_queue": "ucp-jobs.fifo",
            "retry_count": 0,
            "max_retries": 3,
            "next_run_at": datetime.now(UTC),
        },
        {
            "name": UcpCleanupJobName.UCP_AUDIT_LOG_CLEANUP.value,
            "payload": {},
            "status": JobStatus.PENDING.value,
            "cron_expression": "* * * * *",
            "target_queue": "ucp-jobs.fifo",
            "retry_count": 0,
            "max_retries": 3,
            "next_run_at": datetime.now(UTC),
        },
    ]

    try:
        async with provider.session() as session:
            logger.info("ucp_seed_jobs_starting", job_count=len(jobs))
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
                            "cron_expression": row["cron_expression"],
                            "target_queue": row["target_queue"],
                            "next_run_at": datetime.now(UTC),
                        },
                    )
                )
                await session.execute(stmt)
                logger.info("ucp_seed_job_upserted", job_id=job_id, job_name=job_name)
            await session.commit()
            logger.info("ucp_seed_jobs_completed")
    except Exception:
        logger.exception("ucp_seed_jobs_failed")
        sys.exit(1)
    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
