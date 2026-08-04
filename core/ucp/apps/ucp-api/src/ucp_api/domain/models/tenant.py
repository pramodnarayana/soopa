from datetime import datetime, timezone
from typing import List, Literal, Optional

from ucp_api.core.exceptions import AppSubscriptionError, TenantRenameError
from ucp_api.domain.models.aggregate_root import AggregateRoot
from ucp_api.domain.events.tenant_events import (
    TenantProvisionedEvent,
    AppSubscribedEvent,
    AppUnsubscribedEvent,
)

class Tenant(AggregateRoot):
    ID_PREFIX = "ten"

    def __init__(
        self,
        id: str,
        name: str,
        idp_tenant_id: Optional[str],
        status: Literal["active", "inactive"],
        created_at: datetime,
        updated_at: datetime,
        subscriptions: Optional[List[str]] = None,
    ):
        super().__init__()
        self.id = id
        self.name = name
        self.idp_tenant_id = idp_tenant_id
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at
        self.subscriptions = subscriptions if subscriptions is not None else []

    @classmethod
    def create(
        cls,
        id: str,
        name: str,
        idp_tenant_id: Optional[str],
        subscriptions: Optional[List[str]] = None,
    ) -> "Tenant":
        now = datetime.now(timezone.utc)
        tenant = cls(
            id=id,
            name=name,
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
                subscriptions=tenant.subscriptions.copy()
            )
        )
        return tenant

    def rename(self, new_name: str) -> None:
        if not new_name or not new_name.strip():
            raise TenantRenameError("Tenant name cannot be empty.")
        self.name = new_name.strip()
        self.updated_at = datetime.now(timezone.utc)

    def subscribe(self, app_slug: str) -> None:
        if self.status != "active":
            raise AppSubscriptionError("Cannot subscribe an inactive tenant to an app.")
        if app_slug in self.subscriptions:
            raise AppSubscriptionError(f"Tenant is already subscribed to '{app_slug}'.")
        
        self.subscriptions.append(app_slug)
        self.updated_at = datetime.now(timezone.utc)
        self.add_domain_event(
            AppSubscribedEvent(
                tenant_id=self.id,
                tenant_name=self.name,
                app_slug=app_slug
            )
        )

    def unsubscribe_from_app(self, app_slug: str) -> None:
        try:
            self.subscriptions.remove(app_slug)
            self.updated_at = datetime.now(timezone.utc)
            self.add_domain_event(
                AppUnsubscribedEvent(
                    tenant_id=self.id,
                    app_slug=app_slug
                )
            )
        except ValueError:
            raise AppSubscriptionError(f"Tenant is not subscribed to '{app_slug}'.")

    def change_status(self, new_status: Literal["active", "inactive"]) -> None:
        if self.status != new_status:
            self.status = new_status
            self.updated_at = datetime.now(timezone.utc)
