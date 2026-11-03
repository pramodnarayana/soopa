"""Unit tests for IpTraceEvent domain model."""

from __future__ import annotations

from ip.engine.domain.enums import PipelineStage
from ip.engine.domain.trace.enums import (
    TraceEventStatus,
)
from ip.engine.domain.trace.trace_event import IpTraceEvent
from strace.domain import TraceEvent


def test_ip_trace_event_creation() -> None:
    entry = IpTraceEvent.create(
        tenant_id="ten_1",
        trace_id="ip_trc_1",
        correlation_id="CORR-1",
        stage=PipelineStage.NORMALIZE,
        status=TraceEventStatus.SUCCESS,
        summary_message="Normalized load LD-99 into canonical TMS Load",
    )
    assert isinstance(entry, TraceEvent)
    assert isinstance(entry, IpTraceEvent)
    assert entry.id.startswith("ip_trace_evt_")
    assert entry.stage == PipelineStage.NORMALIZE
    assert entry.status == TraceEventStatus.SUCCESS
    assert entry.summary_message == "Normalized load LD-99 into canonical TMS Load"
