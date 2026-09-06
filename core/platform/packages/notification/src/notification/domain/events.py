from dataclasses import dataclass

from seedwork.domain.types import JsonDict
from seedwork.events import DomainEvent


@dataclass(frozen=True)
class NotificationDispatchedEvent(DomainEvent):
    tenant_id: str
    channel: str
    subject: str | None
    content: str
    data: JsonDict
    id: str

    @property
    def event_name(self) -> str:
        return f"{self.channel.lower()}.requested"

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id
