from dataclasses import dataclass

from seedwork.events import DomainEvent
from seedwork.models import AggregateRoot, TracedAggregateRoot, TraceEvent


@dataclass(frozen=True)
class DummyEvent(DomainEvent):
    aggregate_id: str

    @property
    def event_name(self) -> str:
        return "dummy"

    def get_routing_tenant_id(self) -> str | None:
        return None


class DummyAggregate(AggregateRoot):
    ID_PREFIX = "dummy"


def test_new_id_uses_aggregate_prefix_and_12_random_bytes():
    aggregate_id = DummyAggregate.new_id()
    prefix, random_hex = aggregate_id.split("_", maxsplit=1)

    assert prefix == "dummy"
    assert len(random_hex) == 32
    assert int(random_hex, 16) >= 0


def test_aggregate_root_initializes_empty_events():
    aggregate = DummyAggregate()
    assert aggregate.domain_events == []


def test_add_domain_event():
    aggregate = DummyAggregate()
    event = DummyEvent(aggregate_id="123")
    aggregate.add_domain_event(event)
    assert len(aggregate.domain_events) == 1
    assert aggregate.domain_events[0] == event


def test_clear_domain_events():
    aggregate = DummyAggregate()
    event = DummyEvent(aggregate_id="123")
    aggregate.add_domain_event(event)
    assert len(aggregate.domain_events) == 1
    aggregate.clear_domain_events()
    assert len(aggregate.domain_events) == 0


def test_domain_events_property_bypassed_init():
    # Simulate deserialization bypassing __init__
    class BypassedAggregate(AggregateRoot):
        def __new__(cls):
            return super().__new__(cls)

    aggregate = object.__new__(BypassedAggregate)
    assert aggregate.domain_events == []
    aggregate.add_domain_event(DummyEvent(aggregate_id="123"))
    assert len(aggregate.domain_events) == 1
    aggregate.clear_domain_events()
    assert len(aggregate.domain_events) == 0


def test_traced_aggregate_root_and_trace_event() -> None:
    class SampleTracedRoot(TracedAggregateRoot):
        ID_PREFIX = "test"

    root = SampleTracedRoot(
        trace_id="trc_001",
        tenant_id="ten_001",
        correlation_id="corr_external_999",
    )

    assert root.trace_id == "trc_001"
    assert root.tenant_id == "ten_001"
    assert root.correlation_id == "corr_external_999"
    assert root.parent_trace_id is None
    assert root.original_trace_id is None
    assert root.replay_count == 0
    assert root.trace_events == []

    event = TraceEvent(
        id="evt_001",
        tenant_id="ten_001",
        trace_id="trc_001",
        event_type="INGESTION_COMPLETED",
        actor="GATEWAY",
        correlation_id="corr_external_999",
        metadata={"file_name": "load_tender.edi", "records": 10},
    )

    root.add_trace_event(event)
    assert len(root.trace_events) == 1
    assert root.trace_events[0].correlation_id == "corr_external_999"
    assert root.trace_events[0].created_at is not None
    assert root.trace_events[0].metadata == {"file_name": "load_tender.edi", "records": 10}

    root.clear_trace_events()
    assert len(root.trace_events) == 0
