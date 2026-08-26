import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, Literal

import structlog
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from identity_worker.adapters.inbound.workers.identity_event_dispatcher import (
    IdentityEventDispatcher,
)
from identity_worker.adapters.inbound.workers.identity_outbox_relay import IdentityOutboxRelay
from identity_worker.adapters.inbound.workers.sqs_identity_event_consumer import (
    SqsIdentityEventConsumer,
)
from identity_worker.adapters.outbound.database.postgres_identity_outbox_repository import (
    PostgresIdentityOutboxRepository,
)
from identity_worker.adapters.outbound.identity_provider.dummy_identity_provider import (
    DummyIdentityProviderPort,
)
from identity_worker.adapters.outbound.identity_provider.zitadel_identity_provider import (
    ZitadelIdentityProviderPort,
)
from identity_worker.adapters.outbound.identity_provider.zitadel_organizations_adapter import (
    ZitadelOrganizationsAdapter,
)
from identity_worker.adapters.outbound.identity_provider.zitadel_projects_adapter import (
    ZitadelProjectsAdapter,
)
from identity_worker.adapters.outbound.identity_provider.zitadel_users_adapter import (
    ZitadelUsersAdapter,
)
from identity_worker.adapters.outbound.messaging.identity_sns_outbox_publisher import (
    IdentitySnsOutboxPublisher,
)
from identity_worker.application.use_cases.identity_outbox_processor_use_case import (
    IdentityOutboxProcessorUseCase,
)
from identity_worker.application.use_cases.identity_sync_service import IdentitySyncService
from identity_worker.bootstrap.config import get_settings
from identity_worker.ports.outbound.identity_provider_port import IdentityProviderPort
from identity_worker.ports.outbound.user_identity_provider_port import UserIdentityProviderPort

logger = structlog.get_logger(__name__)


class TenantProvisionedPayload(BaseModel):
    tenant_id: str


class UserCreatedPayload(BaseModel):
    user_id: str
    tenant_id: str
    email: str
    first_name: str
    last_name: str
    role: str


class UserUpdatedPayload(BaseModel):
    idp_user_id: str
    tenant_id: str
    first_name: str
    last_name: str
    role: str


class UserRoleAssignedPayload(BaseModel):
    user_id: str
    idp_user_id: str | None = None
    tenant_id: str
    role_name: str


class UserStatusToggledPayload(BaseModel):
    idp_user_id: str
    tenant_id: str
    action: Literal["activate", "deactivate"]


class UserDeletedPayload(BaseModel):
    idp_user_id: str


class WorkerContainer:
    """Dependency Injection container for the Identity Worker."""

    def __init__(self) -> None:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL environment variable is required")
        if database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        self.database_url = database_url
        self.settings = get_settings()

        self._engine = create_async_engine(self.database_url, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )

        self.outbox_relay: IdentityOutboxRelay | None = None
        self.events_consumer: IdentityEventDispatcher | None = None

    def wire(self) -> None:
        self._wire_outbox_relay()
        self._wire_events_consumer()

    def _wire_outbox_relay(self) -> None:
        outbox_repo = PostgresIdentityOutboxRepository(self.session_factory)
        outbox_pub = IdentitySnsOutboxPublisher(
            topic_arn=self.settings.sns_identity_events_topic_arn,
            endpoint_url=self.settings.aws_endpoint_url,
        )
        outbox_processor = IdentityOutboxProcessorUseCase(
            repository=outbox_repo,
            publisher=outbox_pub,
        )
        self.outbox_relay = IdentityOutboxRelay(
            processor=outbox_processor,
            database_url=self.database_url,
        )

    def _register_identity_handlers(
        self,
        consumer: IdentityEventDispatcher,
        identity_service: IdentitySyncService,
    ) -> None:
        async def identity_tenant_provisioned_handler(event: Any) -> None:
            payload = TenantProvisionedPayload.model_validate(event.payload)
            await identity_service.handle_tenant_provisioned(payload.tenant_id)

        async def identity_user_created_handler(event: Any) -> None:
            payload = UserCreatedPayload.model_validate(event.payload)
            await identity_service.handle_user_created(
                user_id=payload.user_id,
                tenant_id=payload.tenant_id,
                email=payload.email,
                first_name=payload.first_name,
                last_name=payload.last_name,
                role=payload.role,
            )

        async def identity_user_updated_handler(event: Any) -> None:
            payload = UserUpdatedPayload.model_validate(event.payload)
            await identity_service.handle_user_updated(
                idp_user_id=payload.idp_user_id,
                tenant_id=payload.tenant_id,
                first_name=payload.first_name,
                last_name=payload.last_name,
                role=payload.role,
            )

        async def identity_user_role_assigned_handler(event: Any) -> None:
            payload = UserRoleAssignedPayload.model_validate(event.payload)
            await identity_service.handle_user_role_assigned(
                user_id=payload.user_id,
                idp_user_id=payload.idp_user_id,
                tenant_id=payload.tenant_id,
                role=payload.role_name,
            )

        async def identity_user_status_toggled_handler(event: Any) -> None:
            payload = UserStatusToggledPayload.model_validate(event.payload)
            await identity_service.handle_user_status_toggled(
                idp_user_id=payload.idp_user_id,
                tenant_id=payload.tenant_id,
                action=payload.action,
            )

        async def identity_user_deleted_handler(event: Any) -> None:
            payload = UserDeletedPayload.model_validate(event.payload)
            await identity_service.handle_user_deleted(idp_user_id=payload.idp_user_id)

        consumer.subscribe("tenant.provisioned", identity_tenant_provisioned_handler)
        consumer.subscribe("UserInvited", identity_user_created_handler)
        consumer.subscribe("UserUpdated", identity_user_updated_handler)
        consumer.subscribe("user_role_assigned", identity_user_role_assigned_handler)
        consumer.subscribe("UserStatusToggled", identity_user_status_toggled_handler)
        consumer.subscribe("UserDeleted", identity_user_deleted_handler)

    def _wire_events_consumer(self) -> None:
        @asynccontextmanager
        async def session_factory() -> AsyncGenerator[AsyncSession, None]:
            async with self.session_factory() as session:
                yield session

        if self.settings.app_env in ("local", "test"):
            idp: IdentityProviderPort = DummyIdentityProviderPort()
            idp_users: UserIdentityProviderPort = DummyIdentityProviderPort()
        else:
            project_provider = ZitadelProjectsAdapter()
            org_provider = ZitadelOrganizationsAdapter(project_provider=project_provider)

            idp = ZitadelIdentityProviderPort(
                org_provider=org_provider, session_factory=session_factory
            )
            idp_users = ZitadelUsersAdapter()

        identity_service = IdentitySyncService(
            identity_provider=idp, user_identity_provider=idp_users, session_factory=session_factory
        )

        self.events_consumer = IdentityEventDispatcher(
            event_consumer=SqsIdentityEventConsumer(
                queue_name=self.settings.sqs_identity_sync_queue_name,
                endpoint_url=self.settings.aws_endpoint_url,
            )
        )

        self._register_identity_handlers(self.events_consumer, identity_service)

    async def dispose(self) -> None:
        if self._engine:
            await self._engine.dispose()
