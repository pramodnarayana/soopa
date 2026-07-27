import asyncio
import contextlib
import logging
import os

from config.settings import get_settings
from database.connection import DatabaseRouter
from database.models import DatabaseShard, Tenant, TenantUser, User
from dotenv import load_dotenv
from sqlalchemy.future import select

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def seed_database() -> None:
    """Seeds the database with required initial infrastructure and default Tenant 0."""
    logger.info("Starting database seed...")
    settings = get_settings()

    db_router = DatabaseRouter(settings.database.global_url)

    async_gen = db_router.get_global_session()
    session = await async_gen.__anext__()

    try:
        # 1. Seed Database Shards
        logger.info("Seeding Database Shards...")
        shard_result = await session.execute(select(DatabaseShard).filter_by(name="shard_1"))
        shard = shard_result.scalar_one_or_none()

        if not shard or not shard.id:
            shard = DatabaseShard(
                name="shard_1",
                dsn="postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1",
            )
            session.add(shard)
            await session.flush()  # To get the ID
            logger.info("Created shard_1.")

        # 2. Seed Default Tenant 0
        logger.info("Seeding Host Company as Tenant 0...")
        tenant_result = await session.execute(select(Tenant).filter_by(id="0"))
        tenant_obj = tenant_result.scalar_one_or_none()

        if not tenant_obj:
            # Tenant 0 is the host company; it uses a dedicated schema "tenant_host"
            tenant_obj = Tenant(
                id="0",
                name="Host Company",
                shard_id=shard.id,
                tier="standard",
                shard_schema="tenant_host",
            )
            session.add(tenant_obj)
            await session.flush()
            logger.info("Created Tenant 0 (Host Company).")
        else:
            needs_repair = False
            if tenant_obj.shard_schema != "tenant_host":
                tenant_obj.shard_schema = "tenant_host"
                needs_repair = True
            if tenant_obj.shard_id != shard.id:
                tenant_obj.shard_id = shard.id
                needs_repair = True
            if needs_repair:
                session.add(tenant_obj)
                await session.flush()
                logger.info("Repaired Tenant 0 shard_id and shard_schema to shard_1/tenant_host.")

        # 3. Seed Default User
        admin_email = os.getenv("SYSTEM_ADMIN_EMAIL")
        admin_name = os.getenv("SYSTEM_ADMIN_NAME", "System Admin")

        if admin_email:
            logger.info("Seeding Default Admin User...")
            user_result = await session.execute(select(User).filter_by(email=admin_email))
            user = user_result.scalar_one_or_none()

            if not user or not user.id:
                user = User(email=admin_email, name=admin_name)
                session.add(user)
                await session.flush()
                logger.info("Created Admin User.")

            # Map user to Tenant 0 idempotently
            mapping_result = await session.execute(
                select(TenantUser).filter_by(tenant_id=tenant_obj.id, user_id=user.id)
            )
            tenant_user = mapping_result.scalar_one_or_none()
            if not tenant_user:
                tenant_user = TenantUser(tenant_id=tenant_obj.id, user_id=user.id, role="admin")
                session.add(tenant_user)
                logger.info("Mapped Admin User to Tenant 0.")
        else:
            logger.info("SYSTEM_ADMIN_EMAIL not provided. Skipping default admin creation.")

        # 4. Seed Core System Jobs
        logger.info("Seeding Core System Jobs...")
        from dataclasses import dataclass
        from datetime import UTC, datetime

        from database.models.scheduled_job import ScheduledJob
        from worker.core.scheduler.models import (
            AppNamespace,
            JobName,
            JobStatus,
            TargetQueue,
            Timezone,
        )

        @dataclass(frozen=True)
        class JobDefinition:
            name: JobName
            target_queue: str | None = None
            app_namespace: str | None = None
            default_interval_seconds: int | None = None
            min_interval_seconds: int | None = None
            max_interval_seconds: int | None = None
            default_cron_expression: str | None = None
            default_timezone: str | None = None
            max_retries: int = 3

        SYSTEM_JOB_REGISTRY: list[JobDefinition] = [
            JobDefinition(
                name=JobName.OUTBOX_SWEEPER,
                target_queue=TargetQueue.EDI_ORCHESTRATOR_JOBS.value,
                app_namespace=AppNamespace.EDI.value,
                default_interval_seconds=60,
                min_interval_seconds=10,
                max_interval_seconds=300,
            ),
            JobDefinition(
                name=JobName.DATA_RETENTION_CLEANUP,
                target_queue=TargetQueue.EDI_ORCHESTRATOR_JOBS.value,
                app_namespace=AppNamespace.EDI.value,
                default_cron_expression="0 2 * * *",
                default_timezone=Timezone.UTC.value,
            ),
        ]

        now = datetime.now(UTC)
        for job_def in SYSTEM_JOB_REGISTRY:
            job_result = await session.execute(select(ScheduledJob).filter_by(name=job_def.name.value))
            job = job_result.scalar_one_or_none()

            if not job:
                job = ScheduledJob(
                    name=job_def.name.value,
                    payload={},
                    status=JobStatus.PENDING.value,
                    target_queue=job_def.target_queue,
                    app_namespace=job_def.app_namespace,
                    interval_seconds=job_def.default_interval_seconds,
                    cron_expression=job_def.default_cron_expression,
                    timezone=job_def.default_timezone,
                    min_interval_seconds=job_def.min_interval_seconds,
                    max_interval_seconds=job_def.max_interval_seconds,
                    retry_count=0,
                    max_retries=job_def.max_retries,
                    created_at=now,
                    updated_at=now,
                    next_run_at=now,
                )
                session.add(job)
                logger.info(f"Created system job: {job_def.name.value}.")
            else:
                # Always sync canonical config bounds from the registry,
                # ensuring existing rows stay consistent after schema migrations.
                job.target_queue = job_def.target_queue
                job.app_namespace = job_def.app_namespace
                job.cron_expression = job_def.default_cron_expression
                job.timezone = job_def.default_timezone
                job.min_interval_seconds = job_def.min_interval_seconds
                job.max_interval_seconds = job_def.max_interval_seconds
                logger.info(f"Synced config for system job: {job_def.name.value}.")

            await session.flush()

        await session.commit()
        logger.info("Database seed completed successfully.")

    except Exception as e:
        logger.error(f"Seed failed: {e}")
        await session.rollback()
        raise
    finally:
        with contextlib.suppress(StopAsyncIteration):
            await async_gen.__anext__()
        await db_router.close_all()


if __name__ == "__main__":
    asyncio.run(seed_database())
