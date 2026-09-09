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


def test_domain_event_idempotency_key_generation():
    event1 = DummyEvent(id="123")
    event2 = DummyEventNoId()

    # Should generate a prefixed ID
    assert event1.idempotency_key.startswith("sys_id_")
    assert event2.idempotency_key.startswith("sys_id_")
    assert event1.idempotency_key != event2.idempotency_key

    assert event1.event_name == "dummy.event"
    assert event1.get_routing_tenant_id() == "tenant-1"

    assert event2.event_name == "dummy.event.noid"
    assert event2.get_routing_tenant_id() is None
