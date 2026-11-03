"""EDI Domain Events."""

from dataclasses import dataclass

from seedwork.events import DomainEvent

from edi.domain.types import JsonValue

ProvisioningEventType = str


@dataclass(frozen=True)
class ProvisioningEvent(DomainEvent):
    tenant_id: str
    event_type: ProvisioningEventType
    resource_id: str | None = None

    @property
    def event_name(self) -> str:
        return str(self.event_type)

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class OutboxEvent:
    id: str
    tenant_id: str
    event_type: str
    payload: dict[str, JsonValue]
    idempotency_key: str | None = None
