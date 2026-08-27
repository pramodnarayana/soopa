from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from seedwork.models import AggregateRoot

from ucp.domain.events import (
    AppSubscribedEvent,
    AppUnsubscribedEvent,
    TenantDeletedEvent,
    TenantNameUpdatedEvent,
    TenantProvisionedEvent,
    TenantStatusToggledEvent,
)
from ucp.domain.exceptions import AppSubscriptionError, TenantRenameError


@dataclass
class TenantSubscription:
    app_id: str
    status: Literal["active", "inactive"]


class Tenant(AggregateRoot):
    ID_PREFIX = "ten"

    def __init__(
        self,
        id: str,
        name: str,
        slug: str,
        idp_tenant_id: str | None,
        status: Literal["active", "inactive"],
        created_at: datetime,
        updated_at: datetime,
        subscriptions: list[TenantSubscription] | None = None,
    ):
        super().__init__()
        self.id = id
        self.name = name
        self.slug = slug
        self.idp_tenant_id = idp_tenant_id
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at
        self.deleted_at: datetime | None = None
        self.subscriptions = subscriptions if subscriptions is not None else []

    @classmethod
    def create(
        cls,
        id: str,
        name: str,
        slug: str,
        idp_tenant_id: str | None,
        subscriptions: list[TenantSubscription] | None = None,
    ) -> "Tenant":
        now = datetime.now(UTC)
        tenant = cls(
            id=id,
            name=name,
            slug=slug,
            idp_tenant_id=idp_tenant_id,
            status="active",
            created_at=now,
            updated_at=now,
            subscriptions=subscriptions,
        )
        tenant.add_domain_event(
            TenantProvisionedEvent(
                tenant_id=id,
                tenant_name=name,
                subscriptions=tuple(s.app_id for s in tenant.subscriptions if s.status == "active"),
            )
        )
        return tenant

    def rename(self, new_name: str) -> None:
        if not new_name or not new_name.strip():
            raise TenantRenameError("Tenant name cannot be empty.")
        self.name = new_name.strip()
        self.updated_at = datetime.now(UTC)
        if self.idp_tenant_id:
            self.add_domain_event(TenantNameUpdatedEvent(org_id=self.idp_tenant_id, name=self.name))

    def set_idp_tenant_id(self, idp_tenant_id: str) -> None:
        if self.idp_tenant_id:
            if self.idp_tenant_id == idp_tenant_id:
                # Idempotent no-op when re-setting to the same ID
                return
            raise ValueError(
                f"Tenant already has a different IDP organization associated: {self.idp_tenant_id}"
            )
        self.idp_tenant_id = idp_tenant_id
        self.updated_at = datetime.now(UTC)

    def subscribe(self, app_id: str) -> None:
        if self.status != "active":
            raise AppSubscriptionError("Cannot subscribe an inactive tenant to an app.")

        sub = next((s for s in self.subscriptions if s.app_id == app_id), None)
        if sub:
            if sub.status == "active":
                raise AppSubscriptionError(f"Tenant is already subscribed to '{app_id}'.")
            sub.status = "active"
        else:
            self.subscriptions.append(TenantSubscription(app_id=app_id, status="active"))

        self.updated_at = datetime.now(UTC)
        self.add_domain_event(AppSubscribedEvent(tenant_id=self.id, app_id=app_id))

    def unsubscribe_from_app(self, app_id: str) -> None:
        sub = next((s for s in self.subscriptions if s.app_id == app_id), None)
        if not sub or sub.status == "inactive":
            raise AppSubscriptionError(f"Tenant is not subscribed to '{app_id}'.")

        sub.status = "inactive"
        self.updated_at = datetime.now(UTC)
        self.add_domain_event(AppUnsubscribedEvent(tenant_id=self.id, app_id=app_id))

    def change_status(self, new_status: Literal["active", "inactive"]) -> None:
        if self.status != new_status:
            self.status = new_status
            self.updated_at = datetime.now(UTC)
            if self.idp_tenant_id:
                self.add_domain_event(
                    TenantStatusToggledEvent(
                        org_id=self.idp_tenant_id, active=self.status == "active"
                    )
                )

    def mark_deleted(self) -> None:
        """Logically deletes this tenant.

        Sets deleted_at to signal soft deletion and emits TenantDeletedEvent
        to cascade the deletion to the IdP organization asynchronously.
        Raises AlreadyDeletedError if the tenant has already been deleted.
        """
        if self.deleted_at is not None:
            raise ValueError(f"Tenant '{self.id}' has already been deleted.")
        self.deleted_at = datetime.now(UTC)
        self.updated_at = self.deleted_at
        if self.idp_tenant_id:
            self.add_domain_event(TenantDeletedEvent(org_id=self.idp_tenant_id))
