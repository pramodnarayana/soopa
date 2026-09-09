from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Literal

import structlog
from database.provider import get_async_engine
from identity.domain.constants import IdentityEventType
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from identity_worker.adapters.inbound.workers.identity_event_dispatcher import (
    IdentityEventDispatcher,
)
from identity_worker.adapters.outbound.database.identity_sync_repository import (
    PostgresIdentitySyncUnitOfWork,
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
from identity_worker.application.use_cases.identity_sync_service import IdentitySyncService
from identity_worker.bootstrap.config import Settings, get_settings
from identity_worker.ports.inbound.identity_event_consumer_port import IdentityEventMessage
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

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

        database_url = self.settings.database_url
        if not database_url:
            raise ValueError("database_url is required in Settings")

        if database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        self.database_url = database_url

        self._engine = get_async_engine(self.database_url)
        self.session_factory = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )

    def wire(self) -> None:
        self._wire_events_consumer()

    def _register_identity_handlers(
        self,
        consumer: IdentityEventDispatcher,
        identity_service: IdentitySyncService,
    ) -> None:
        async def identity_tenant_provisioned_handler(event: IdentityEventMessage) -> None:
            payload = TenantProvisionedPayload.model_validate(event.payload)
            await identity_service.handle_tenant_provisioned(payload.tenant_id)

        async def identity_user_created_handler(event: IdentityEventMessage) -> None:
            payload = UserCreatedPayload.model_validate(event.payload)
            await identity_service.handle_user_created(
                user_id=payload.user_id,
                tenant_id=payload.tenant_id,
                email=payload.email,
                first_name=payload.first_name,
                last_name=payload.last_name,
                role=payload.role,
            )

        async def identity_user_updated_handler(event: IdentityEventMessage) -> None:
            payload = UserUpdatedPayload.model_validate(event.payload)
            await identity_service.handle_user_updated(
                idp_user_id=payload.idp_user_id,
                tenant_id=payload.tenant_id,
                first_name=payload.first_name,
                last_name=payload.last_name,
                role=payload.role,
            )

        async def identity_user_role_assigned_handler(event: IdentityEventMessage) -> None:
            payload = UserRoleAssignedPayload.model_validate(event.payload)
            await identity_service.handle_user_role_assigned(
                user_id=payload.user_id,
                idp_user_id=payload.idp_user_id,
                tenant_id=payload.tenant_id,
                role=payload.role_name,
            )

        async def identity_user_status_toggled_handler(event: IdentityEventMessage) -> None:
            payload = UserStatusToggledPayload.model_validate(event.payload)
            await identity_service.handle_user_status_toggled(
                idp_user_id=payload.idp_user_id,
                tenant_id=payload.tenant_id,
                action=payload.action,
            )

        async def identity_user_deleted_handler(event: IdentityEventMessage) -> None:
            payload = UserDeletedPayload.model_validate(event.payload)
            await identity_service.handle_user_deleted(idp_user_id=payload.idp_user_id)

        consumer.subscribe(
            IdentityEventType.TENANT_PROVISIONED, identity_tenant_provisioned_handler
        )
        consumer.subscribe(IdentityEventType.USER_INVITED, identity_user_created_handler)
        consumer.subscribe(IdentityEventType.USER_UPDATED, identity_user_updated_handler)
        consumer.subscribe(
            IdentityEventType.USER_ROLE_ASSIGNED, identity_user_role_assigned_handler
        )
        consumer.subscribe(
            IdentityEventType.USER_STATUS_TOGGLED, identity_user_status_toggled_handler
        )
        consumer.subscribe(IdentityEventType.USER_DELETED, identity_user_deleted_handler)

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
            identity_provider=idp,
            user_identity_provider=idp_users,
            uow_factory=lambda: PostgresIdentitySyncUnitOfWork(session_factory),
        )

        self.events_dispatcher = IdentityEventDispatcher()

        self._register_identity_handlers(self.events_dispatcher, identity_service)

        # Wire up the new centralized SqsConsumerManager from pubsub

        identity_sync_consumer = AwsSqsConsumer(
            queue_url=self.settings.sqs_identity_sync_queue_url,
            region_name=self.settings.aws_region,
            endpoint_url=self.settings.aws_endpoint_url,
        )
        self.events_consumer = SqsConsumerManager(
            consumer=identity_sync_consumer,
            queue_name="identity-events.fifo",
            handler=self.events_dispatcher.dispatch_raw,
        )

    async def dispose(self) -> None:
        if self._engine:
            await self._engine.dispose()
