from collections.abc import Awaitable, Callable
from typing import Literal

from identity.domain.constants import IdentityEventType
from pydantic import BaseModel

from identity_worker.adapters.inbound.workers.identity_event_dispatcher import (
    IdentityEventDispatcher,
)
from identity_worker.application.use_cases.identity_sync_service import IdentitySyncService
from identity_worker.ports.inbound.identity_event_consumer_port import IdentityEventMessage


class TenantProvisionedPayload(BaseModel):
    tenant_id: str


class TenantNameUpdatedPayload(BaseModel):
    org_id: str
    name: str


class TenantStatusToggledPayload(BaseModel):
    org_id: str
    active: bool


class TenantDeletedPayload(BaseModel):
    org_id: str


class AppSubscribedPayload(BaseModel):
    tenant_id: str
    idp_project_id: str | None = None


class AppUnsubscribedPayload(BaseModel):
    tenant_id: str
    app_id: str
    idp_project_id: str | None = None


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


class IdentityEventHandlers:
    """Inbound SQS payload translator delegating validated events to IdentitySyncService."""

    def __init__(self, identity_service: IdentitySyncService) -> None:
        self._service = identity_service

    async def on_tenant_provisioned(self, event: IdentityEventMessage) -> None:
        payload = TenantProvisionedPayload.model_validate(event.payload)
        await self._service.handle_tenant_provisioned(payload.tenant_id)

    async def on_tenant_name_updated(self, event: IdentityEventMessage) -> None:
        payload = TenantNameUpdatedPayload.model_validate(event.payload)
        await self._service.handle_tenant_name_updated(payload.org_id, payload.name)

    async def on_tenant_status_toggled(self, event: IdentityEventMessage) -> None:
        payload = TenantStatusToggledPayload.model_validate(event.payload)
        await self._service.handle_tenant_status_toggled(payload.org_id, payload.active)

    async def on_tenant_deleted(self, event: IdentityEventMessage) -> None:
        payload = TenantDeletedPayload.model_validate(event.payload)
        await self._service.handle_tenant_deleted(payload.org_id)

    async def on_app_subscribed(self, event: IdentityEventMessage) -> None:
        payload = AppSubscribedPayload.model_validate(event.payload)
        await self._service.handle_app_subscribed(
            tenant_id=payload.tenant_id, idp_project_id=payload.idp_project_id
        )

    async def on_app_unsubscribed(self, event: IdentityEventMessage) -> None:
        payload = AppUnsubscribedPayload.model_validate(event.payload)
        await self._service.handle_app_unsubscribed(
            tenant_id=payload.tenant_id, idp_project_id=payload.idp_project_id
        )

    async def on_user_created(self, event: IdentityEventMessage) -> None:
        payload = UserCreatedPayload.model_validate(event.payload)
        await self._service.handle_user_created(
            user_id=payload.user_id,
            tenant_id=payload.tenant_id,
            email=payload.email,
            first_name=payload.first_name,
            last_name=payload.last_name,
            role=payload.role,
        )

    async def on_user_updated(self, event: IdentityEventMessage) -> None:
        payload = UserUpdatedPayload.model_validate(event.payload)
        await self._service.handle_user_updated(
            idp_user_id=payload.idp_user_id,
            tenant_id=payload.tenant_id,
            first_name=payload.first_name,
            last_name=payload.last_name,
            role=payload.role,
        )

    async def on_user_role_assigned(self, event: IdentityEventMessage) -> None:
        payload = UserRoleAssignedPayload.model_validate(event.payload)
        await self._service.handle_user_role_assigned(
            user_id=payload.user_id,
            idp_user_id=payload.idp_user_id,
            tenant_id=payload.tenant_id,
            role=payload.role_name,
        )

    async def on_user_status_toggled(self, event: IdentityEventMessage) -> None:
        payload = UserStatusToggledPayload.model_validate(event.payload)
        await self._service.handle_user_status_toggled(
            idp_user_id=payload.idp_user_id,
            tenant_id=payload.tenant_id,
            action=payload.action,
        )

    async def on_user_deleted(self, event: IdentityEventMessage) -> None:
        payload = UserDeletedPayload.model_validate(event.payload)
        await self._service.handle_user_deleted(idp_user_id=payload.idp_user_id)

    def routes(
        self,
    ) -> tuple[tuple[str, Callable[[IdentityEventMessage], Awaitable[None]]], ...]:
        return (
            (IdentityEventType.TENANT_PROVISIONED, self.on_tenant_provisioned),
            (IdentityEventType.TENANT_NAME_UPDATED, self.on_tenant_name_updated),
            (IdentityEventType.TENANT_STATUS_TOGGLED, self.on_tenant_status_toggled),
            (IdentityEventType.TENANT_DELETED, self.on_tenant_deleted),
            (IdentityEventType.APP_SUBSCRIBED, self.on_app_subscribed),
            (IdentityEventType.APP_UNSUBSCRIBED, self.on_app_unsubscribed),
            (IdentityEventType.USER_INVITED, self.on_user_created),
            (IdentityEventType.USER_UPDATED, self.on_user_updated),
            (IdentityEventType.USER_ROLE_ASSIGNED, self.on_user_role_assigned),
            (IdentityEventType.USER_STATUS_TOGGLED, self.on_user_status_toggled),
            (IdentityEventType.USER_DELETED, self.on_user_deleted),
        )


def register_identity_handlers(
    consumer: IdentityEventDispatcher,
    identity_service: IdentitySyncService,
) -> None:
    handlers = IdentityEventHandlers(identity_service)
    for event_type, handler in handlers.routes():
        consumer.subscribe(event_type, handler)
