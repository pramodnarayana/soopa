import asyncio
import functools
from collections.abc import Callable
from typing import Any

import structlog
from dotenv import load_dotenv
from edi.adapters.outbound.database.connection import DatabaseRouter
from edi.adapters.outbound.database.tenant_resolver import (
    TenantResolver,
)
from edi.adapters.outbound.database.tenant_uow_provider import (
    TenantUowProvider,
)
from edi.adapters.outbound.pipeline.as2 import HttpxAS2DeliveryClient
from edi.adapters.outbound.pipeline.http import HttpxDeliveryClient
from edi.adapters.outbound.pipeline.sftp import ParamikoSftpClient
from edi.adapters.outbound.pipeline.transformer import BotsTransformerAdapter
from edi.adapters.outbound.security.network import validate_target_url
from edi.application.use_cases.pipeline.delivery_router_use_case import DeliveryRouterUseCase
from edi.application.use_cases.pipeline.delivery_use_case import DeliveryUseCase
from edi.application.use_cases.pipeline.dispatch_inbound_transform_use_case import (
    DispatchInboundTransformUseCase,
)
from edi.application.use_cases.pipeline.dispatch_outbound_transform_use_case import (
    DispatchOutboundTransformUseCase,
)
from edi.application.use_cases.pipeline.pipeline_lifecycle_use_case import PipelineLifecycleUseCase
from edi.config.settings import get_settings
from edi.core.pipeline.delivery.as2 import As2DeliveryStrategy
from edi.core.pipeline.delivery.sftp import SftpDeliveryStrategy
from edi.core.pipeline.delivery.webhook import WebhookDeliveryStrategy
from edi.domain.events import MessageQueueName, PipelineEventType
from edi.ports.outbound.data_plane_unit_of_work_port import DataPlaneUnitOfWorkPort

from worker.adapters.aws_secrets_manager import AwsSecretsManagerSecretStore
from worker.adapters.edi_data_plane_sqs_outbox_publisher import (
    EdiDataPlaneSqsOutboxPublisherAdapter,
)
from worker.adapters.inbound.workers.edi_data_plane_events_sqs_consumer import (
    EdiDataPlaneEventMessage,
    EdiDataPlaneEventsSqsConsumer,
)
from worker.adapters.sqs_poller import poll_sqs_queue
from worker.domain.edi_data_plane_route_registry import EdiDataPlaneRouteRegistry
from worker.domain.scheduler.models import JobName

load_dotenv()
logger = structlog.get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    aws_endpoint = settings.aws.endpoint_url
    s3_bucket = "soopaedi-dev"

    db_router = DatabaseRouter(global_db_url=settings.database.global_url)
    resolver = TenantResolver(db_router)

    # ─────────────────────────────────────────────────────────────
    # Inbound SQS Adapters (Hexagonal: Protocol Translation Only)
    # ─────────────────────────────────────────────────────────────
    transformer = BotsTransformerAdapter()
    vault = AwsSecretsManagerSecretStore()

    uow_provider = TenantUowProvider(
        resolver=resolver,
        db_router=db_router,
        settings=settings,
        s3_bucket=s3_bucket,
        aws_endpoint=aws_endpoint,
    )

    http_delivery = HttpxDeliveryClient(validator=validate_target_url)
    sftp_delivery = ParamikoSftpClient()
    as2_delivery = HttpxAS2DeliveryClient(validator=validate_target_url)

    def router_factory(uow: DataPlaneUnitOfWorkPort) -> DeliveryRouterUseCase:
        strategies = {
            "webhook_id": WebhookDeliveryStrategy(uow, http_delivery, vault),
            "sftp_partner_id": SftpDeliveryStrategy(uow, sftp_delivery, vault),
            "as2_partner_id": As2DeliveryStrategy(uow, as2_delivery, vault),
        }
        return DeliveryRouterUseCase(uow=uow, strategies=strategies)

    registry = EdiDataPlaneRouteRegistry()

    async def run_inbound(e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]) -> None:
        async with uow_fact() as uow:
            await DispatchInboundTransformUseCase(uow, transformer, settings).execute(e.trace_id)

    async def run_outbound(e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]) -> None:
        async with uow_fact() as uow:
            await DispatchOutboundTransformUseCase(uow, transformer, settings).execute(e.trace_id)

    async def run_transform_lifecycle(
        e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]
    ) -> None:
        async with uow_fact() as uow:
            await PipelineLifecycleUseCase(uow).handle_transform_completed(e.payload)

    async def run_delivery_lifecycle(
        e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]
    ) -> None:
        async with uow_fact() as uow:
            await PipelineLifecycleUseCase(uow).handle_delivery_completed(e.payload)

    async def run_deliver(e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]) -> None:
        await DeliveryUseCase(uow_factory=uow_fact, router_factory=router_factory).execute(
            trace_id=e.trace_id, idempotency_key=e.idempotency_key
        )

    registry.register(
        event_type=PipelineEventType.TRANSFORM_EVENT.value,
        direction="INBOUND",
        factory=run_inbound,
    )
    registry.register(
        event_type=PipelineEventType.TRANSFORM_EVENT.value,
        direction="OUTBOUND",
        factory=run_outbound,
    )
    registry.register(
        event_type=PipelineEventType.TRANSFORM_COMPLETED.value,
        direction=None,
        factory=run_transform_lifecycle,
    )
    registry.register(
        event_type=PipelineEventType.DELIVER_EVENT.value,
        direction=None,
        factory=run_deliver,
    )
    registry.register(
        event_type=PipelineEventType.DELIVERY_COMPLETED.value,
        direction=None,
        factory=run_delivery_lifecycle,
    )

    async def route_event(event: EdiDataPlaneEventMessage) -> None:
        uow_factory = await uow_provider.get_uow_factory(event.tenant_id)
        await registry.route(event, uow_factory)

    consumer = EdiDataPlaneEventsSqsConsumer(callback=route_event)

    transform_task = asyncio.create_task(
        poll_sqs_queue(
            MessageQueueName.TRANSFORM_QUEUE,
            consumer.handle,
            aws_endpoint,
        )
    )

    lifecycle_task = asyncio.create_task(
        poll_sqs_queue(
            MessageQueueName.LIFECYCLE_QUEUE,
            consumer.handle,
            aws_endpoint,
        )
    )

    deliver_task = asyncio.create_task(
        poll_sqs_queue(
            MessageQueueName.DELIVER_QUEUE,
            consumer.handle,
            aws_endpoint,
        )
    )

    # ─────────────────────────────────────────────────────────────
    # Scheduled Jobs (Cleanup & Sweeper)
    # ─────────────────────────────────────────────────────────────
    from worker.adapters.inbound.jobs.edi_audit_log_cleanup_job import EdiAuditLogCleanupJobHandler
    from worker.adapters.inbound.jobs.edi_control_plane_outbox_cleanup_job import (
        EdiControlPlaneOutboxCleanupJobHandler,
    )
    from worker.adapters.inbound.jobs.edi_control_plane_outbox_sweeper_job import (
        EdiControlPlaneOutboxSweeperJobHandler,
    )
    from worker.adapters.inbound.jobs.edi_data_plane_outbox_cleanup_job import (
        EdiDataPlaneOutboxCleanupJobHandler,
    )
    from worker.adapters.inbound.jobs.edi_data_plane_outbox_sweeper_job import (
        EdiDataPlaneOutboxSweeperJobHandler,
    )
    from worker.adapters.inbound.jobs.edi_idempotency_cleanup_job import (
        EdiIdempotencyCleanupJobHandler,
    )
    from worker.adapters.outbound.database.postgres_edi_audit_log_cleanup_repository import (
        SqlAlchemyEdiAuditLogCleanupRepository,
    )
    from worker.adapters.outbound.database.postgres_edi_control_plane_outbox_cleanup_repository import (
        SqlAlchemyEdiControlPlaneOutboxCleanupRepository,
    )
    from worker.adapters.outbound.database.postgres_edi_data_plane_outbox_cleanup_repository import (
        SqlAlchemyEdiDataPlaneOutboxCleanupRepository,
    )
    from worker.adapters.outbound.database.postgres_edi_idempotency_cleanup_repository import (
        SqlAlchemyEdiIdempotencyCleanupRepository,
    )
    from worker.adapters.postgres_outbox_relay_repository import PostgresOutboxRelayRepository
    from worker.application.use_cases.edi_audit_log_cleanup_use_case import (
        EdiAuditLogCleanupUseCase,
    )
    from worker.application.use_cases.edi_control_plane_outbox_cleanup_use_case import (
        EdiControlPlaneOutboxCleanupUseCase,
    )
    from worker.application.use_cases.edi_control_plane_outbox_sweeper_use_case import (
        EdiControlPlaneOutboxSweeperUseCase,
    )
    from worker.application.use_cases.edi_data_plane_outbox_cleanup_use_case import (
        EdiDataPlaneOutboxCleanupUseCase,
    )
    from worker.application.use_cases.edi_data_plane_outbox_sweeper_use_case import (
        EdiDataPlaneOutboxSweeperUseCase,
    )
    from worker.application.use_cases.edi_idempotency_cleanup_use_case import (
        EdiIdempotencyCleanupUseCase,
    )
    from worker.domain.job_registry import JobHandlerRegistry

    message_publisher = EdiDataPlaneSqsOutboxPublisherAdapter(
        endpoint_url=settings.aws.endpoint_url,
        region=settings.aws.resolved_region,
    )
    outbox_relay_repository = PostgresOutboxRelayRepository(db_router=db_router)

    edi_cp_outbox_cleanup_repo = SqlAlchemyEdiControlPlaneOutboxCleanupRepository(
        db_router=db_router
    )
    edi_dp_outbox_cleanup_repo = SqlAlchemyEdiDataPlaneOutboxCleanupRepository(db_router=db_router)
    edi_idemp_cleanup_repo = SqlAlchemyEdiIdempotencyCleanupRepository(db_router=db_router)
    edi_audit_cleanup_repo = SqlAlchemyEdiAuditLogCleanupRepository(db_router=db_router)

    orchestrator_sweeper_use_case = EdiDataPlaneOutboxSweeperUseCase(db_router, message_publisher)
    provisioning_sweeper_use_case = EdiControlPlaneOutboxSweeperUseCase(outbox_relay_repository)

    job_registry = JobHandlerRegistry()
    job_registry.register(
        JobName.EDI_ORCHESTRATOR_OUTBOX_SWEEPER.value,
        EdiDataPlaneOutboxSweeperJobHandler(orchestrator_sweeper_use_case),
    )
    job_registry.register(
        JobName.EDI_PROVISIONING_OUTBOX_SWEEPER.value,
        EdiControlPlaneOutboxSweeperJobHandler(provisioning_sweeper_use_case),
    )
    job_registry.register(
        JobName.EDI_CONTROL_PLANE_OUTBOX_CLEANUP.value,
        EdiControlPlaneOutboxCleanupJobHandler(
            EdiControlPlaneOutboxCleanupUseCase(edi_cp_outbox_cleanup_repo)
        ),
    )
    job_registry.register(
        JobName.EDI_DATA_PLANE_OUTBOX_CLEANUP.value,
        EdiDataPlaneOutboxCleanupJobHandler(
            EdiDataPlaneOutboxCleanupUseCase(edi_dp_outbox_cleanup_repo)
        ),
    )
    job_registry.register(
        JobName.EDI_IDEMPOTENCY_CLEANUP.value,
        EdiIdempotencyCleanupJobHandler(EdiIdempotencyCleanupUseCase(edi_idemp_cleanup_repo)),
    )
    job_registry.register(
        JobName.EDI_AUDIT_LOG_CLEANUP.value,
        EdiAuditLogCleanupJobHandler(EdiAuditLogCleanupUseCase(edi_audit_cleanup_repo)),
    )

    from worker.data.scheduled_jobs_handler import process_scheduled_job

    scheduled_jobs_task = asyncio.create_task(
        poll_sqs_queue(
            "edi-orchestrator-jobs",
            functools.partial(process_scheduled_job, registry=job_registry),
            aws_endpoint,
        )
    )

    # ─────────────────────────────────────────────────────────────
    # Run all workers concurrently
    # ─────────────────────────────────────────────────────────────
    try:
        await asyncio.gather(transform_task, lifecycle_task, deliver_task, scheduled_jobs_task)
    finally:
        logger.info("data_worker.shutting_down_gracefully")
        transform_task.cancel()
        lifecycle_task.cancel()
        deliver_task.cancel()
        scheduled_jobs_task.cancel()

        import contextlib

        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(
                transform_task,
                lifecycle_task,
                deliver_task,
                scheduled_jobs_task,
                return_exceptions=True,
            )

        await db_router.close_all()


if __name__ == "__main__":
    asyncio.run(main())
