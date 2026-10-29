import asyncio
import hashlib
import os
import sys
from datetime import UTC, datetime

import structlog
from database.models.scheduling import ScheduledJob
from database.utils import normalize_to_asyncpg
from dotenv import load_dotenv
from edi.domain.enums import EdiJobName
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv()
logger = structlog.get_logger(__name__)


async def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        logger.error("DATABASE_URL environment variable is not set.")
        sys.exit(1)

    database_url = normalize_to_asyncpg(database_url)
    engine = create_async_engine(database_url)

    # Note: Using cron `* * * * *` means every minute.
    jobs = [
        {
            "name": EdiJobName.EDI_CONTROL_PLANE_OUTBOX_SWEEPER.value,
            "payload": {},
            "status": "PENDING",
            "cron_expression": "* * * * *",
            "target_queue": "edi-control-plane-jobs.fifo",
            "retry_count": 0,
            "max_retries": 3,
            "next_run_at": datetime.now(UTC),
        },
        {
            "name": EdiJobName.EDI_DATA_PLANE_OUTBOX_SWEEPER.value,
            "payload": {},
            "status": "PENDING",
            "cron_expression": "* * * * *",
            "target_queue": "edi-data-plane-jobs.fifo",
            "retry_count": 0,
            "max_retries": 3,
            "next_run_at": datetime.now(UTC),
        },
        {
            "name": EdiJobName.EDI_CONTROL_PLANE_OUTBOX_CLEANUP.value,
            "payload": {},
            "status": "PENDING",
            "cron_expression": "* * * * *",  # Changed from 0 * * * * for development visibility
            "target_queue": "edi-control-plane-jobs.fifo",
            "retry_count": 0,
            "max_retries": 3,
            "next_run_at": datetime.now(UTC),
        },
        {
            "name": EdiJobName.EDI_DATA_PLANE_OUTBOX_CLEANUP.value,
            "payload": {},
            "status": "PENDING",
            "cron_expression": "* * * * *",  # Changed from 0 * * * * for development visibility
            "target_queue": "edi-data-plane-jobs.fifo",
            "retry_count": 0,
            "max_retries": 3,
            "next_run_at": datetime.now(UTC),
        },
        {
            "name": EdiJobName.EDI_DATA_RETENTION_CLEANUP.value,
            "payload": {},
            "status": "PENDING",
            "cron_expression": "0 2 * * *",  # Nightly at 2am
            "target_queue": "edi-data-plane-jobs.fifo",
            "retry_count": 0,
            "max_retries": 3,
            "next_run_at": datetime.now(UTC),
        },
    ]

    try:
        async with engine.begin() as conn:
            logger.info("Seeding EDI scheduler jobs...")

            for job_data in jobs:
                # Generate a deterministic, cryptographically-secure-looking ID based on the job name
                # to satisfy the "job_{bytes}" enterprise ID generation standard while keeping the seed idempotent.
                name_hash = hashlib.sha256(job_data["name"].encode()).hexdigest()[:24]
                job_id = f"job_{name_hash}"
                job_data["id"] = job_id

                stmt = (
                    pg_insert(ScheduledJob)
                    .values(**job_data)
                    .on_conflict_do_update(
                        index_elements=[ScheduledJob.id],
                        set_={
                            "name": job_data["name"],
                            "cron_expression": job_data["cron_expression"],
                            "target_queue": job_data["target_queue"],
                            "next_run_at": datetime.now(UTC),
                        },
                    )
                )
                await conn.execute(stmt)
                logger.info("Successfully seeded job.", job_id=job_id, job_name=job_data["name"])

            logger.info("All EDI scheduler jobs seeded successfully.")
    except Exception:
        logger.exception("Failed to seed EDI scheduler jobs.")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
