"""Unit tests for the shared core/platform/packages/trace capability package."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from seedwork.domain.types import JsonValue
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from strace.adapters import (
    TenantTraceableOrmModel,
    TenantTraceLineageOrmModel,
    TraceEventMixin,
    drain_trace_events,
)
from strace.application import (
    TraceLineageContext,
    TraceLineageItemDTO,
    TraceStageAttemptRow,
    aggregate_trace_lineage_attempts,
    extract_deepest_lineage_context,
)
from strace.domain import (
    TracedAggregateRoot,
    TraceErrorDetails,
    TraceEvent,
    TraceEventType,
    TraceReplayMetadata,
    TraceStatus,
)
from strace.testing import InMemoryTraceRepository


class _UnitOrmBase(DeclarativeBase):
    pass


class _UnitStageOrm(_UnitOrmBase, TenantTraceableOrmModel):
    __tablename__ = "unit_trace_stage_orm"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)


class _UnitTraceEventOrm(_UnitOrmBase, TraceEventMixin):
    __tablename__ = "unit_trace_event_orm"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


@dataclass(frozen=True, kw_only=True)
class FakeStageEntity:
    trace_id: str
    correlation_id: str | None
    parent_trace_id: str | None
    original_trace_id: str | None
    replay_count: int


@dataclass
class FakeTraceableAggregate:
    _events: list[TraceEvent]

    @property
    def trace_events(self) -> list[TraceEvent]:
        return list(self._events)

    def clear_trace_events(self) -> None:
        self._events.clear()


@dataclass(frozen=True, kw_only=True)
class FakeTraceEventOrmRow:
    id: str
    tenant_id: str
    trace_id: str
    correlation_id: str | None
    event_type: str
    actor: str
    metadata_: dict[str, JsonValue] | None
    created_at: datetime


class RecordingAdder:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)


def test_orm_mixins_declare_expected_columns_and_indexes() -> None:
    assert issubclass(_UnitStageOrm, TenantTraceLineageOrmModel)
    stage_cols = set(_UnitStageOrm.__table__.columns.keys())
    assert {
        "id",
        "tenant_id",
        "trace_id",
        "correlation_id",
        "parent_trace_id",
        "original_trace_id",
        "replay_count",
    } <= stage_cols

    event_cols = set(_UnitTraceEventOrm.__table__.columns.keys())
    assert {
        "id",
        "tenant_id",
        "trace_id",
        "correlation_id",
        "event_type",
        "actor",
        "metadata_",
        "created_at",
    } <= event_cols


def test_trace_error_details_and_replay_metadata_serialization() -> None:
    err = TraceErrorDetails(
        reason="HTTP_503",
        detail="Service Unavailable",
        response_status_code=503,
        failure_category="TRANSIENT",
        retry_after_seconds=15,
        next_attempt=2,
    )
    assert err.to_dict() == {
        "reason": "HTTP_503",
        "detail": "Service Unavailable",
        "response_status_code": 503,
        "failure_category": "TRANSIENT",
        "retry_after_seconds": 15,
        "next_attempt": 2,
    }

    minimal_err = TraceErrorDetails(reason="SCHEMA_ERROR")
    assert minimal_err.to_dict() == {"reason": "SCHEMA_ERROR"}

    replay_meta = TraceReplayMetadata(
        parent_trace_id="trc_parent",
        original_trace_id="trc_root",
        replay_count=3,
    )
    assert replay_meta.to_dict() == {
        "parent_trace_id": "trc_parent",
        "original_trace_id": "trc_root",
        "replay_count": 3,
    }


def test_extract_deepest_lineage_context_prioritizes_deepest_non_empty_stage() -> None:
    l1 = FakeStageEntity(
        trace_id="trc_1",
        correlation_id="ORD-100",
        parent_trace_id=None,
        original_trace_id="trc_1",
        replay_count=0,
    )
    l5 = FakeStageEntity(
        trace_id="trc_2",
        correlation_id="ORD-100",
        parent_trace_id="trc_1",
        original_trace_id="trc_1",
        replay_count=1,
    )
    ctx = extract_deepest_lineage_context(
        trace_id="trc_2",
        stages_deepest_first=((l5,), (), (l1,)),
    )
    assert isinstance(ctx, TraceLineageContext)
    assert ctx.parent_trace_id == "trc_1"
    assert ctx.original_trace_id == "trc_1"
    assert ctx.replay_count == 1
    assert ctx.correlation_id == "ORD-100"

    empty_ctx = extract_deepest_lineage_context(
        trace_id="trc_empty",
        stages_deepest_first=((), ()),
        fallback_correlation_id="FALLBACK-1",
    )
    assert empty_ctx.parent_trace_id is None
    assert empty_ctx.original_trace_id == "trc_empty"
    assert empty_ctx.replay_count == 0
    assert empty_ctx.correlation_id == "FALLBACK-1"


def test_aggregate_trace_lineage_attempts_merges_stages_in_pipeline_order() -> None:
    t0 = datetime.now(UTC)
    t1 = t0 + timedelta(seconds=5)

    stage_1 = [
        TraceStageAttemptRow(
            trace_id="trc_root",
            correlation_id="MTR-100",
            status=TraceStatus.INGESTED,
            primary_layer="L1_INGEST",
            created_at=t0,
            replay_count=0,
            parent_trace_id=None,
            original_trace_id="trc_root",
        )
    ]
    stage_3 = [
        TraceStageAttemptRow(
            trace_id="trc_root",
            correlation_id=None,
            status=TraceStatus.FAILED,
            primary_layer="L5_DELIVER",
            created_at=t0 + timedelta(seconds=1),
            replay_count=0,
            parent_trace_id=None,
            original_trace_id="trc_root",
        ),
        TraceStageAttemptRow(
            trace_id="trc_replay_1",
            correlation_id="MTR-100",
            status=TraceStatus.DELIVERED,
            primary_layer="L5_DELIVER",
            created_at=t1,
            replay_count=1,
            parent_trace_id="trc_root",
            original_trace_id="trc_root",
        ),
    ]

    merged = aggregate_trace_lineage_attempts(
        stage_batches_in_pipeline_order=(stage_1, stage_3),
        fallback_root_trace_id="trc_root",
    )
    assert len(merged) == 2
    assert merged[0].trace_id == "trc_root"
    assert merged[0].correlation_id == "MTR-100"
    assert merged[0].status == TraceStatus.FAILED
    assert merged[0].primary_layer == "L5_DELIVER"
    assert merged[0].created_at == t0

    assert merged[1].trace_id == "trc_replay_1"
    assert merged[1].status == TraceStatus.DELIVERED
    assert merged[1].replay_count == 1
    assert merged[1].parent_trace_id == "trc_root"


def test_drain_trace_events_persists_and_clears_aggregate_events() -> None:
    now = datetime.now(UTC)
    evt = TraceEvent(
        id="evt_01",
        trace_id="trc_01",
        tenant_id="ten_01",
        event_type="L1_INGEST_RECEIVED",
        actor="SYSTEM",
        correlation_id="MTR-100",
        metadata={"layer": "L1_INGEST"},
        created_at=now,
    )
    agg = FakeTraceableAggregate(_events=[evt])
    adder = RecordingAdder()

    drain_trace_events(
        session=adder,
        aggregate=agg,
        orm_factory=FakeTraceEventOrmRow,
    )

    assert len(adder.added) == 1
    row = adder.added[0]
    assert isinstance(row, FakeTraceEventOrmRow)
    assert row.id == "evt_01"
    assert row.trace_id == "trc_01"
    assert row.correlation_id == "MTR-100"
    assert agg.trace_events == []


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
        event_type=TraceEventType.RECEIVED,
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

    # Also verify lazy initialization when _trace_events is missing (e.g., unpickled instances)
    unpickled_root = object.__new__(SampleTracedRoot)
    assert unpickled_root.trace_events == []
    del unpickled_root._trace_events
    unpickled_root.add_trace_event(event)
    assert len(unpickled_root.trace_events) == 1


@pytest.mark.asyncio
async def test_in_memory_trace_repository_satisfies_trace_repository_port() -> None:
    repo = InMemoryTraceRepository()
    t0 = datetime.now(UTC)
    t1 = t0 + timedelta(seconds=10)

    e1 = TraceEvent(
        id="evt_1",
        tenant_id="ten_1",
        trace_id="trc_root",
        event_type=TraceEventType.RECEIVED,
        actor="SYSTEM",
        correlation_id="PO-100",
        created_at=t0,
    )
    e2 = TraceEvent(
        id="evt_2",
        tenant_id="ten_1",
        trace_id="trc_root",
        event_type=TraceEventType.DELIVERY_FAILED,
        actor="SYSTEM",
        correlation_id="PO-100",
        created_at=t1,
    )
    await repo.save_trace_event(e2)
    await repo.save_all_trace_events([e1])

    listed = await repo.list_trace_events("ten_1", "trc_root")
    assert [e.id for e in listed] == ["evt_1", "evt_2"]

    repo.seed_lineage_item(
        "ten_1",
        TraceLineageItemDTO(
            trace_id="trc_root",
            correlation_id="PO-100",
            status=TraceStatus.FAILED,
            primary_layer="STAGE_1",
            created_at=t0,
            replay_count=0,
            parent_trace_id=None,
            original_trace_id="trc_root",
        ),
    )
    repo.seed_lineage_item(
        "ten_1",
        TraceLineageItemDTO(
            trace_id="trc_child",
            correlation_id="PO-100",
            status=TraceStatus.DELIVERED,
            primary_layer="STAGE_2",
            created_at=t1,
            replay_count=1,
            parent_trace_id="trc_root",
            original_trace_id="trc_root",
        ),
    )

    assert await repo.resolve_root_trace_id("ten_1", "trc_child") == "trc_root"
    assert await repo.resolve_root_trace_id("ten_1", "trc_unknown") == "trc_unknown"

    lineage = await repo.get_trace_lineage("ten_1", "trc_child")
    assert [item.trace_id for item in lineage] == ["trc_root", "trc_child"]

    corr = await repo.find_traces_by_correlation_id("ten_1", "PO-100", limit=1)
    assert len(corr) == 1
    assert corr[0].trace_id == "trc_child"

    failed_recent = await repo.list_recent_traces("ten_1", status=TraceStatus.FAILED, limit=10)
    assert [item.trace_id for item in failed_recent] == ["trc_root"]

    replayed_recent = await repo.list_recent_traces("ten_1", min_replay_count=1, limit=10)
    assert [item.trace_id for item in replayed_recent] == ["trc_child"]
