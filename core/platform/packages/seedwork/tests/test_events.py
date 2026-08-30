import uuid
from dataclasses import dataclass

from seedwork.events import DomainEvent


@dataclass(frozen=True)
class DummyEvent(DomainEvent):
    id: str

    @property
    def event_name(self) -> str:
        return "dummy.event"

    def get_routing_tenant_id(self) -> str | None:
        return "tenant-1"


@dataclass(frozen=True)
class DummyEventNoId(DomainEvent):
    @property
    def event_name(self) -> str:
        return "dummy.event.noid"

    def get_routing_tenant_id(self) -> str | None:
        return None


def test_domain_event_idempotency_key_with_id():
    event = DummyEvent(id="event-123")
    assert event.idempotency_key == "event-123"
    assert event.event_name == "dummy.event"
    assert event.get_routing_tenant_id() == "tenant-1"


def test_domain_event_idempotency_key_without_id():
    event = DummyEventNoId()
    key1 = event.idempotency_key
    key2 = event.idempotency_key
    # Should generate a UUID and memoize it
    assert key1 == key2
    assert isinstance(uuid.UUID(key1), uuid.UUID)
    assert event.event_name == "dummy.event.noid"
    assert event.get_routing_tenant_id() is None
