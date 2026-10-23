"""Unit tests for TimelineEntry and IpTraceEvent domain models."""

from __future__ import annotations

from ip.engine.domain.enums import PipelineLayer, TimelineStatus
from ip.engine.domain.models.timeline_entry import IpTraceEvent, TimelineEntry
from seedwork.models import TraceEvent


def test_timeline_entry_creation() -> None:
    entry = TimelineEntry.create(
        tenant_id="ten_1",
        trace_id="ip_trc_1",
        correlation_id="CORR-1",
        layer=PipelineLayer.L3_NORMALIZE,
        status=TimelineStatus.SUCCESS,
        summary_message="Normalized load LD-99 into canonical TMS Load",
    )
    assert isinstance(entry, TraceEvent)
    assert isinstance(entry, IpTraceEvent)
    assert entry.id.startswith("ip_trace_evt_")
    assert entry.layer == PipelineLayer.L3_NORMALIZE
    assert entry.status == TimelineStatus.SUCCESS
    assert entry.summary_message == "Normalized load LD-99 into canonical TMS Load"
