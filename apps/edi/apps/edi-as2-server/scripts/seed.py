import asyncio
import contextlib
import logging
import os

from config.settings import get_settings
from database.connection import DatabaseRouter
from database.models import App, DatabaseShard, ShardRegistry, Tenant, TenantUser, User
from dotenv import load_dotenv
from identity.domain.identity_context import PLATFORM_TENANT_ID
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
        logger.info("Seeding Host Company as Tenant %s...", PLATFORM_TENANT_ID)
        tenant_result = await session.execute(select(Tenant).filter_by(id=PLATFORM_TENANT_ID))
        tenant_obj = tenant_result.scalar_one_or_none()

        if not tenant_obj:
            # Tenant 0 is the host company
            tenant_obj = Tenant(
                id=PLATFORM_TENANT_ID,
                name="Host Company",
            )
            session.add(tenant_obj)
            await session.flush()
            logger.info("Created Tenant %s (Host Company).", PLATFORM_TENANT_ID)

        # Ensure App exists
        app_result = await session.execute(select(App).filter_by(slug="platform"))
        platform_app = app_result.scalar_one_or_none()

        if not platform_app:
            platform_app = App(slug="platform", name="Platform")
            session.add(platform_app)
            await session.flush()
            logger.info("Created platform App.")

        # Ensure ShardRegistry exists
        ts_result = await session.execute(
            select(ShardRegistry).filter_by(
                tenant_id=PLATFORM_TENANT_ID, app_id=platform_app.id, shard_id=shard.id
            )
        )
        tenant_shard = ts_result.scalar_one_or_none()

        if not tenant_shard:
            tenant_shard = ShardRegistry(
                tenant_id=PLATFORM_TENANT_ID,
                app_id=platform_app.id,
                shard_id=shard.id,
            )
            session.add(tenant_shard)
            await session.flush()
            logger.info("Created ShardRegistry mapping for Tenant %s.", PLATFORM_TENANT_ID)
        else:
            logger.info("ShardRegistry mapping already exists for Tenant %s.", PLATFORM_TENANT_ID)

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

            # Map user to Tenant PLATFORM_TENANT_ID idempotently
            mapping_result = await session.execute(
                select(TenantUser).filter_by(tenant_id=tenant_obj.id, user_id=user.id)
            )
            tenant_user = mapping_result.scalar_one_or_none()
            if not tenant_user:
                tenant_user = TenantUser(tenant_id=tenant_obj.id, user_id=user.id, role="admin")
                session.add(tenant_user)
                logger.info("Mapped Admin User to Tenant %s.", PLATFORM_TENANT_ID)
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
                default_cron_expression="* * * * *",
                default_timezone=Timezone.UTC.value,
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
            job_result = await session.execute(
                select(ScheduledJob).filter_by(name=job_def.name.value)
            )
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
