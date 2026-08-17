from ucp.domain.events.base import DomainEvent


class TenantProvisionedEvent(DomainEvent):
    tenant_id: str
    tenant_name: str
    subscriptions: list[str]

    @property
    def event_name(self) -> str:
        return "tenant.provisioned"

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


class AppSubscribedEvent(DomainEvent):
    tenant_id: str
    app_id: str

    @property
    def event_name(self) -> str:
        return "app.subscribed"

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


class AppUnsubscribedEvent(DomainEvent):
    tenant_id: str
    app_id: str

    @property
    def event_name(self) -> str:
        return "app.unsubscribed"

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


class TenantNameUpdatedEvent(DomainEvent):
    org_id: str
    name: str

    @property
    def event_name(self) -> str:
        return "TenantNameUpdated"

    def get_routing_tenant_id(self) -> str | None:
        return self.org_id


class TenantStatusToggledEvent(DomainEvent):
    org_id: str
    active: bool

    @property
    def event_name(self) -> str:
        return "TenantStatusToggled"

    def get_routing_tenant_id(self) -> str | None:
        return self.org_id


class TenantDeletedEvent(DomainEvent):
    org_id: str

    @property
    def event_name(self) -> str:
        return "TenantDeleted"

    def get_routing_tenant_id(self) -> str | None:
        return self.org_id
