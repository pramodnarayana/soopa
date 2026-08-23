import asyncio
import contextlib

import structlog
from dotenv import load_dotenv
from edi.adapters.outbound.database.connection import DatabaseRouter
from edi.config.settings import get_settings
from identity.domain.identity_context import PLATFORM_TENANT_ID
from platform_orm.models.identity import Tenant
from sqlalchemy.future import select

load_dotenv()

logger = structlog.get_logger(__name__)


async def seed_database() -> None:
    """Seeds the database with required initial infrastructure and default Tenant 0."""
    logger.info("Starting database seed...")
    settings = get_settings()

    db_router = DatabaseRouter(settings.database.global_url)

    async_gen = db_router.get_global_session()
    session = await async_gen.__anext__()

    try:
        # 1. Assert Core Platform Infrastructure Exists (Read-Only)
        logger.info("Asserting Platform Infrastructure (Tenant %s)...", PLATFORM_TENANT_ID)
        tenant_result = await session.execute(select(Tenant).filter_by(id=PLATFORM_TENANT_ID))
        tenant_obj = tenant_result.scalar_one_or_none()
        if not tenant_obj:
            logger.warning(
                "Platform Master Tenant not found! Ensure UCP seed.ts has been run first."
            )

        # 4. Seed Core System Jobs
        logger.info("Seeding Core System Jobs...")
        from dataclasses import dataclass

        from platform_orm.clients.scheduler import SchedulerClient
        from worker.core.scheduler.models import (
            AppNamespace,
            JobName,
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
                name=JobName.EDI_ORCHESTRATOR_OUTBOX_SWEEPER,
                target_queue=TargetQueue.EDI_ORCHESTRATOR_JOBS.value,
                app_namespace=AppNamespace.EDI.value,
                default_cron_expression="* * * * *",
                default_timezone=Timezone.UTC.value,
            ),
            JobDefinition(
                name=JobName.EDI_PROVISIONING_OUTBOX_SWEEPER,
                target_queue=TargetQueue.EDI_ORCHESTRATOR_JOBS.value,
                app_namespace=AppNamespace.EDI.value,
                default_cron_expression="* * * * *",
                default_timezone=Timezone.UTC.value,
            ),
            JobDefinition(
                name=JobName.EDI_CONTROL_PLANE_OUTBOX_CLEANUP,
                target_queue=TargetQueue.EDI_ORCHESTRATOR_JOBS.value,
                app_namespace=AppNamespace.EDI.value,
                default_cron_expression="0 2 * * *",
                default_timezone=Timezone.UTC.value,
            ),
            JobDefinition(
                name=JobName.EDI_DATA_PLANE_OUTBOX_CLEANUP,
                target_queue=TargetQueue.EDI_ORCHESTRATOR_JOBS.value,
                app_namespace=AppNamespace.EDI.value,
                default_cron_expression="0 2 * * *",
                default_timezone=Timezone.UTC.value,
            ),
            JobDefinition(
                name=JobName.EDI_IDEMPOTENCY_CLEANUP,
                target_queue=TargetQueue.EDI_ORCHESTRATOR_JOBS.value,
                app_namespace=AppNamespace.EDI.value,
                default_cron_expression="0 2 * * *",
                default_timezone=Timezone.UTC.value,
            ),
            JobDefinition(
                name=JobName.EDI_AUDIT_LOG_CLEANUP,
                target_queue=TargetQueue.EDI_ORCHESTRATOR_JOBS.value,
                app_namespace=AppNamespace.EDI.value,
                default_cron_expression="0 2 * * *",
                default_timezone=Timezone.UTC.value,
            ),
        ]

        scheduler_client = SchedulerClient(session)
        for job_def in SYSTEM_JOB_REGISTRY:
            await scheduler_client.register_job(
                name=job_def.name.value,
                target_queue=str(job_def.target_queue),
                app_namespace=str(job_def.app_namespace),
                cron_expression=job_def.default_cron_expression,
                default_timezone=str(job_def.default_timezone),
                max_retries=job_def.max_retries,
            )
            logger.info(
                "Registered system job via SchedulerClient: {job_def.name.value}.",
                job_def_name_value=job_def.name.value,
            )
            await session.flush()

        await session.commit()
        logger.info("Database seed completed successfully.")

    except Exception:
        logger.exception("Seed failed")

        await session.rollback()
        raise
    finally:
        with contextlib.suppress(StopAsyncIteration):
            await async_gen.__anext__()
        await db_router.close_all()


if __name__ == "__main__":
    asyncio.run(seed_database())
