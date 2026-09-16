import asyncio
import os
import sys

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
            "id": "job_edi_cp_sweeper",
            "name": EdiJobName.EDI_CONTROL_PLANE_OUTBOX_SWEEPER.value,
            "payload": {},
            "status": "PENDING",
            "cron_expression": "* * * * *",
            "target_queue": "edi-control-plane-jobs.fifo",
            "retry_count": 0,
            "max_retries": 3,
        },
        {
            "id": "job_edi_dp_sweeper",
            "name": EdiJobName.EDI_DATA_PLANE_OUTBOX_SWEEPER.value,
            "payload": {},
            "status": "PENDING",
            "cron_expression": "* * * * *",
            "target_queue": "edi-data-plane-jobs.fifo",
            "retry_count": 0,
            "max_retries": 3,
        },
    ]

    try:
        async with engine.begin() as conn:
            logger.info("Seeding EDI scheduler jobs...")

            for job_data in jobs:
                stmt = (
                    pg_insert(ScheduledJob)
                    .values(**job_data)
                    .on_conflict_do_update(
                        index_elements=[ScheduledJob.id],
                        set_={
                            "name": job_data["name"],
                            "cron_expression": job_data["cron_expression"],
                            "target_queue": job_data["target_queue"],
                        },
                    )
                )
                await conn.execute(stmt)
                logger.info("Successfully seeded job.", job_name=job_data["name"])

            logger.info("All EDI scheduler jobs seeded successfully.")
    except Exception:
        logger.exception("Failed to seed EDI scheduler jobs.")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
