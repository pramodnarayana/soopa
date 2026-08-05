from ucp_api.domain.events.base import DomainEvent


class TenantProvisionedEvent(DomainEvent):
    tenant_id: str
    tenant_name: str
    subscriptions: list[str]


class AppSubscribedEvent(DomainEvent):
    tenant_id: str
    tenant_name: str
    app_slug: str


class AppUnsubscribedEvent(DomainEvent):
    tenant_id: str
    app_slug: str
