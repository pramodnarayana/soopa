import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from ucp.adapters.inbound.sqs_ucp_event_listener import SqsUcpEventListener
from ucp.adapters.inbound.workers.ucp_events_sqs_consumer import UcpEventsSqsConsumer
from ucp.adapters.inbound.workers.ucp_outbox_relay import UcpOutboxRelay
from ucp.adapters.outbound.database.postgres_outbox_repository import PostgresOutboxRepository
from ucp.adapters.outbound.database.postgres_ucp_audit_log_cleanup_repository import (
    SqlAlchemyUcpAuditLogCleanupRepository,
)
from ucp.adapters.outbound.database.postgres_ucp_idempotency_cleanup_repository import (
    SqlAlchemyUcpIdempotencyCleanupRepository,
)
from ucp.adapters.outbound.database.postgres_ucp_outbox_cleanup_repository import (
    SqlAlchemyUcpOutboxCleanupRepository,
)
from ucp.adapters.outbound.database.uow import SqlAlchemyUcpUnitOfWork
from ucp.adapters.outbound.identity.dummy_identity_provider import DummyIdentityProvider
from ucp.adapters.outbound.identity.zitadel_identity_provider import ZitadelIdentityProvider
from ucp.adapters.outbound.messaging.ucp_sns_outbox_publisher import UcpSnsOutboxPublisher
from ucp.application.handlers.tenant_deleted_handler import TenantDeletedEventHandler
from ucp.application.services.identity_sync_service import IdentitySyncService
from ucp.application.services.infrastructure_provisioner import InfrastructureProvisioner
from ucp.application.sweep_outbox_use_case import SweepControlPlaneOutboxUseCase
from ucp.application.ucp_audit_log_cleanup_use_case import UcpAuditLogCleanupUseCase
from ucp.application.ucp_idempotency_cleanup_use_case import UcpIdempotencyCleanupUseCase
from ucp.application.ucp_outbox_cleanup_use_case import UcpOutboxCleanupUseCase
from ucp.application.ucp_outbox_processor_use_case import UcpOutboxProcessorUseCase
from ucp.bootstrap.container import Container as CoreContainer
from ucp.core.config import get_settings
from ucp.ports.identity_provider import IdentityProviderPort
from ucp.ports.outbound.user_identity_provider import IUserIdentityProvider
from ucp.ports.uow import UcpUnitOfWorkPort

from ucp_worker.adapters.inbound.jobs.ucp_audit_log_cleanup_job import UcpAuditLogCleanupJobHandler
from ucp_worker.adapters.inbound.jobs.ucp_idempotency_cleanup_job import (
    UcpIdempotencyCleanupJobHandler,
)
from ucp_worker.adapters.inbound.jobs.ucp_outbox_cleanup_job import UcpOutboxCleanupJobHandler
from ucp_worker.adapters.inbound.jobs.ucp_outbox_sweeper_job import UcpOutboxSweeperJobHandler
from ucp_worker.core.job_registry import JobHandlerRegistry
from ucp_worker.core.scheduler.models import JobName

logger = structlog.get_logger(__name__)


class WorkerContainer:
    """Dependency Injection container for the UCP Worker."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.database_url = os.environ.get("DATABASE_URL", "")
        if self.database_url.startswith("postgresql://"):
            self.database_url = self.database_url.replace(
                "postgresql://", "postgresql+asyncpg://", 1
            )

        self._engine = create_async_engine(self.database_url, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )

        self.registry: JobHandlerRegistry | None = None
        self.outbox_relay: UcpOutboxRelay | None = None
        self.events_consumer: UcpEventsSqsConsumer | None = None

    def wire(self) -> None:
        self._wire_scheduled_jobs()
        self._wire_outbox_relay()
        self._wire_events_consumer()

    def _wire_scheduled_jobs(self) -> None:
        outbox_repo = PostgresOutboxRepository(self.session_factory)
        outbox_pub = UcpSnsOutboxPublisher(
            topic_arn=self.settings.sns_tenant_events_topic_arn,
            endpoint_url=self.settings.aws_endpoint_url,
        )
        outbox_cleanup_repo = SqlAlchemyUcpOutboxCleanupRepository(self.session_factory)
        idemp_cleanup_repo = SqlAlchemyUcpIdempotencyCleanupRepository(self.session_factory)
        audit_cleanup_repo = SqlAlchemyUcpAuditLogCleanupRepository(self.session_factory)

        sweeper_use_case = SweepControlPlaneOutboxUseCase(outbox_repo, outbox_pub)

        outbox_cleanup_use_case = UcpOutboxCleanupUseCase(outbox_cleanup_repo)
        idemp_cleanup_use_case = UcpIdempotencyCleanupUseCase(idemp_cleanup_repo)
        audit_cleanup_use_case = UcpAuditLogCleanupUseCase(audit_cleanup_repo)

        self.registry = JobHandlerRegistry()
        self.registry.register(
            JobName.UCP_OUTBOX_SWEEPER.value, UcpOutboxSweeperJobHandler(sweeper_use_case)
        )
        self.registry.register(
            JobName.UCP_OUTBOX_CLEANUP.value,
            UcpOutboxCleanupJobHandler(outbox_cleanup_use_case),
        )
        self.registry.register(
            JobName.UCP_IDEMPOTENCY_CLEANUP.value,
            UcpIdempotencyCleanupJobHandler(idemp_cleanup_use_case),
        )
        self.registry.register(
            JobName.UCP_AUDIT_LOG_CLEANUP.value,
            UcpAuditLogCleanupJobHandler(audit_cleanup_use_case),
        )

    def _wire_outbox_relay(self) -> None:
        outbox_repo = PostgresOutboxRepository(self.session_factory)
        outbox_pub = UcpSnsOutboxPublisher(
            topic_arn=self.settings.sns_tenant_events_topic_arn,
            endpoint_url=self.settings.aws_endpoint_url,
        )
        outbox_processor = UcpOutboxProcessorUseCase(
            repository=outbox_repo,
            publisher=outbox_pub,
        )
        self.outbox_relay = UcpOutboxRelay(
            processor=outbox_processor,
            database_url=self.database_url,
        )

    def _register_identity_handlers(
        self,
        consumer: UcpEventsSqsConsumer,
        identity_service: IdentitySyncService,
        tenant_deleted_handler: TenantDeletedEventHandler,
    ) -> None:
        async def identity_tenant_provisioned_handler(event: Any) -> None:
            await identity_service.handle_tenant_provisioned(event.tenant_id)

        async def identity_user_created_handler(event: Any) -> None:
            payload = event.payload
            await identity_service.handle_user_created(
                user_id=payload["user_id"],
                tenant_id=payload["tenant_id"],
                email=payload["email"],
                first_name=payload["first_name"],
                last_name=payload["last_name"],
                role=payload["role"],
            )

        async def identity_user_updated_handler(event: Any) -> None:
            payload = event.payload
            await identity_service.handle_user_updated(
                idp_user_id=payload["idp_user_id"],
                tenant_id=payload["tenant_id"],
                first_name=payload["first_name"],
                last_name=payload["last_name"],
                role=payload["role"],
            )

        async def identity_user_role_assigned_handler(event: Any) -> None:
            payload = event.payload
            idp_user_id = payload.get("idp_user_id")
            tenant_id = payload.get("tenant_id")
            role_name = payload.get("role_name")
            if idp_user_id and tenant_id and role_name:
                await identity_service.handle_user_role_assigned(
                    idp_user_id=idp_user_id,
                    tenant_id=tenant_id,
                    role=role_name,
                )
            else:
                logger.warning(
                    "identity_user_role_assigned_missing_data", event_id=getattr(event, "id", None)
                )

        async def identity_user_status_toggled_handler(event: Any) -> None:
            payload = event.payload
            await identity_service.handle_user_status_toggled(
                idp_user_id=payload["idp_user_id"],
                tenant_id=payload["tenant_id"],
                action=payload["action"],
            )

        async def identity_user_deleted_handler(event: Any) -> None:
            payload = event.payload
            await identity_service.handle_user_deleted(idp_user_id=payload["idp_user_id"])

        async def tenant_deleted_event_handler(event: Any) -> None:
            payload = event.payload
            tenant_id = payload.get("tenant_id") or event.tenant_id
            if tenant_id:
                await tenant_deleted_handler.handle(tenant_id)
            else:
                logger.error(
                    "tenant_deleted_missing_tenant_id", event_id=getattr(event, "id", None)
                )

        consumer.subscribe("tenant.provisioned", identity_tenant_provisioned_handler)
        consumer.subscribe("TenantDeleted", tenant_deleted_event_handler)
        consumer.subscribe("UserInvited", identity_user_created_handler)
        consumer.subscribe("UserUpdated", identity_user_updated_handler)
        consumer.subscribe("user_role_assigned", identity_user_role_assigned_handler)
        consumer.subscribe("UserStatusToggled", identity_user_status_toggled_handler)
        consumer.subscribe("UserDeleted", identity_user_deleted_handler)

    def _wire_events_consumer(self) -> None:
        core_container = CoreContainer()
        idp: IdentityProviderPort
        idp_users: IUserIdentityProvider

        if os.environ.get("APP_ENV", "production") in ("local", "test"):
            idp = DummyIdentityProvider()
            idp_users = DummyIdentityProvider()  # type: ignore
        else:
            idp = ZitadelIdentityProvider(org_provider=core_container.org_provider())
            idp_users = core_container.user_provider()

        @asynccontextmanager
        async def uow_factory() -> AsyncGenerator[UcpUnitOfWorkPort, None]:
            async with self.session_factory() as session:
                yield SqlAlchemyUcpUnitOfWork(session)

        identity_service = IdentitySyncService(
            identity_provider=idp, user_identity_provider=idp_users, uow_factory=uow_factory
        )

        provisioner = InfrastructureProvisioner(uow_factory)
        tenant_deleted_handler = TenantDeletedEventHandler(uow_factory)

        self.events_consumer = UcpEventsSqsConsumer(
            event_listener=SqsUcpEventListener(
                queue_url=self.settings.sqs_ucp_identity_sync_queue_url,
                endpoint_url=self.settings.aws_endpoint_url,
            )
        )

        consumer = self.events_consumer
        consumer.subscribe("app.subscribed", provisioner.handle_app_subscribed)
        consumer.subscribe("app.unsubscribed", provisioner.handle_app_unsubscribed)

        self._register_identity_handlers(consumer, identity_service, tenant_deleted_handler)

    async def dispose(self) -> None:
        if self._engine:
            await self._engine.dispose()
