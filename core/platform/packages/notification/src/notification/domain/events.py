from dataclasses import dataclass
from typing import Any

from seedwork.events import DomainEvent


@dataclass(frozen=True)
class NotificationDispatchedEvent(DomainEvent):
    tenant_id: str
    channel: str
    subject: str | None
    content: str
    data: dict[str, Any]
    idempotency_key: str

    @property
    def event_name(self) -> str:
        return f"{self.channel.lower()}.requested"

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id
