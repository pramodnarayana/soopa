from dataclasses import dataclass

from seedwork.events import DomainEvent, EventEnvelope, EventProcessingLane


@dataclass(frozen=True)
class DummyEvent(DomainEvent):
    id: str

    @property
    def event_name(self) -> str:
        return "dummy.event"

    def get_routing_tenant_id(self) -> str | None:
        return "tenant-1"


@dataclass(frozen=True)
class DummyBulkTracedEvent(DomainEvent):
    trace_id: str
    correlation_id: str

    @property
    def event_name(self) -> str:
        return "dummy.bulk.event"

    def get_routing_tenant_id(self) -> str | None:
        return "tenant-bulk"

    def get_trace_id(self) -> str | None:
        return self.trace_id

    def get_correlation_id(self) -> str | None:
        return self.correlation_id

    def get_processing_lane(self) -> EventProcessingLane:
        return EventProcessingLane.BULK


@dataclass(frozen=True)
class DummyEventNoId(DomainEvent):
    @property
    def event_name(self) -> str:
        return "dummy.event.noid"

    def get_routing_tenant_id(self) -> str | None:
        return None


def test_domain_event_idempotency_key_generation() -> None:
    event1 = DummyEvent(id="123")
    event2 = DummyEventNoId()

    # Should generate a prefixed ID
    assert event1.idempotency_key.startswith("sys_idemp_")
    assert event2.idempotency_key.startswith("sys_idemp_")
    assert event1.idempotency_key != event2.idempotency_key

    assert event1.event_name == "dummy.event"
    assert event1.get_routing_tenant_id() == "tenant-1"
    assert event1.get_trace_id() is None
    assert event1.get_correlation_id() is None
    assert event1.get_processing_lane() == EventProcessingLane.REALTIME

    assert event2.event_name == "dummy.event.noid"
    assert event2.get_routing_tenant_id() is None


def test_event_envelope_and_domain_event_trace_and_lane_headers() -> None:
    bulk_event = DummyBulkTracedEvent(trace_id="trc_01", correlation_id="MTR-101")
    assert bulk_event.get_trace_id() == "trc_01"
    assert bulk_event.get_correlation_id() == "MTR-101"
    assert bulk_event.get_processing_lane() == EventProcessingLane.BULK

    default_env = EventEnvelope(
        id="evt_1",
        source="ip.data_plane",
        event_type="ip.inbound_record.created",
        tenant_id="t_1",
        idempotency_key="ik_1",
        payload={"record_ids": ["rec_1"]},
    )
    assert default_env.trace_id is None
    assert default_env.correlation_id is None
    assert default_env.lane == EventProcessingLane.REALTIME

    bulk_env = EventEnvelope(
        id="evt_2",
        source="ip.data_plane",
        event_type="ip.replica_record.changed",
        tenant_id="t_1",
        idempotency_key="ik_2",
        payload={"record_ids": ["rep_1", "rep_2"]},
        trace_id="trc_01",
        correlation_id="MTR-101",
        lane=EventProcessingLane.BULK,
    )
    assert bulk_env.trace_id == "trc_01"
    assert bulk_env.correlation_id == "MTR-101"
    assert bulk_env.lane == EventProcessingLane.BULK
