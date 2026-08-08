from ucp.domain.events.base import DomainEvent


class TenantProvisionedEvent(DomainEvent):
    tenant_id: str
    tenant_name: str
    subscriptions: list[str]

    @property
    def event_name(self) -> str:
        return "tenant.provisioned"


class AppSubscribedEvent(DomainEvent):
    tenant_id: str
    app_id: str

    @property
    def event_name(self) -> str:
        return "app.subscribed"


class AppUnsubscribedEvent(DomainEvent):
    tenant_id: str
    app_id: str

    @property
    def event_name(self) -> str:
        return "app.unsubscribed"
