from typing import List

from ucp_api.domain.events.base import DomainEvent


class TenantProvisionedEvent(DomainEvent):
    tenant_id: str
    tenant_name: str
    subscriptions: List[str]


class AppSubscribedEvent(DomainEvent):
    tenant_id: str
    tenant_name: str
    app_slug: str


class AppUnsubscribedEvent(DomainEvent):
    tenant_id: str
    app_slug: str
