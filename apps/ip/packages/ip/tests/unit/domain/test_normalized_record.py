"""Unit tests for NormalizedRecord domain aggregate."""

from __future__ import annotations

from ip.engine.domain.enums import IpTraceEventType
from ip.engine.domain.events import NormalizedRecordCreatedEvent
from ip.engine.domain.models.normalized_record import NormalizedRecord
from strace.domain import TracedAggregateRoot


def test_normalized_record_create_emits_trace_and_domain_event() -> None:
    norm = NormalizedRecord.create(
        tenant_id="ten_01",
        connection_id="ip_conn_01",
        canonical_type="MDM_METER_READING",
        source_id="MTR-100",
        canonical_data={"meter_serial_number": "MTR-100", "kwh_delivered": 19.75},
        trace_id="ip_trc_03",
        correlation_id="corr-03",
    )

    assert isinstance(norm, TracedAggregateRoot)
    assert norm.id.startswith("ip_nrm_")
    assert norm.canonical_type == "MDM_METER_READING"
    assert norm.canonical_data["kwh_delivered"] == 19.75
    assert len(norm.trace_events) == 1
    assert norm.trace_events[0].event_type == IpTraceEventType.L3_NORMALIZED.value
    assert len(norm.domain_events) == 1
    assert isinstance(norm.domain_events[0], NormalizedRecordCreatedEvent)
