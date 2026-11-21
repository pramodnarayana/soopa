"""Pure zero-mock Data Mapper and repository unit tests for SqlAlchemyReplayLedgerRepository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest
from ip.engine.adapters.outbound.database.data_plane.replay_ledger_repository import (
    SqlAlchemyReplayLedgerRepository,
)
from ip.engine.adapters.outbound.database.models.data_plane import IpReplayLedgerModel
from ip.engine.domain.replay.models import IpReplayLedgerRecord
from replay.domain.enums import ReplayStage, ReplayStatus, ReplayTargetType
from seedwork.utils import generate_id
from sqlalchemy.ext.asyncio import AsyncSession


def test_replay_ledger_repository_bidirectional_mapper() -> None:
    now = datetime.now(UTC)
    record = IpReplayLedgerRecord(
        id=generate_id("rpl"),
        tenant_id="tenant_alpha",
        idempotency_key="idem_key_001",
        target_type=ReplayTargetType.BATCH,
        target_id="batch_12345",
        target_stage=ReplayStage.STAGE_1_RAW_INGRESS,
        trace_id="trc_new_001",
        parent_trace_id="trc_parent_001",
        original_trace_id="trc_orig_001",
        correlation_id="corr_001",
        actor="usr_admin",
        reason="Manual backfill correction",
        payload_override={"sampling_rate": 60},
        affected_records=100,
        status=ReplayStatus.IN_FLIGHT,
        error_message=None,
        created_at=now,
        completed_at=None,
    )

    orm_model = SqlAlchemyReplayLedgerRepository._to_orm_model(record)
    assert orm_model.id == record.id
    assert orm_model.tenant_id == "tenant_alpha"
    assert orm_model.idempotency_key == "idem_key_001"
    assert orm_model.target_type == ReplayTargetType.BATCH.value
    assert orm_model.target_id == "batch_12345"
    assert orm_model.target_stage == ReplayStage.STAGE_1_RAW_INGRESS.value
    assert orm_model.trace_id == "trc_new_001"
    assert orm_model.parent_trace_id == "trc_parent_001"
    assert orm_model.original_trace_id == "trc_orig_001"
    assert orm_model.correlation_id == "corr_001"
    assert orm_model.actor == "usr_admin"
    assert orm_model.reason == "Manual backfill correction"
    assert orm_model.payload_override == {"sampling_rate": 60}
    assert orm_model.affected_records == 100
    assert orm_model.status == ReplayStatus.IN_FLIGHT.value
    assert orm_model.error_message is None
    assert orm_model.created_at == now
    assert orm_model.completed_at is None

    round_trip_domain = SqlAlchemyReplayLedgerRepository._to_domain_model(orm_model)
    assert round_trip_domain.id == record.id
    assert round_trip_domain.tenant_id == record.tenant_id
    assert round_trip_domain.idempotency_key == record.idempotency_key
    assert round_trip_domain.target_type == record.target_type
    assert round_trip_domain.target_id == record.target_id
    assert round_trip_domain.target_stage == record.target_stage
    assert round_trip_domain.trace_id == record.trace_id
    assert round_trip_domain.parent_trace_id == record.parent_trace_id
    assert round_trip_domain.original_trace_id == record.original_trace_id
    assert round_trip_domain.correlation_id == record.correlation_id
    assert round_trip_domain.actor == record.actor
    assert round_trip_domain.reason == record.reason
    assert round_trip_domain.payload_override == record.payload_override
    assert round_trip_domain.affected_records == record.affected_records
    assert round_trip_domain.status == record.status
    assert round_trip_domain.error_message == record.error_message
    assert round_trip_domain.created_at == record.created_at
    assert round_trip_domain.completed_at == record.completed_at


def test_replay_ledger_repository_update_orm_from_domain() -> None:
    now = datetime.now(UTC)
    orm = IpReplayLedgerModel(
        id="rpl_01",
        tenant_id="tenant_01",
        idempotency_key="idem_01",
        target_type="BATCH",
        target_id="target_01",
        target_stage="STAGE_1_RAW_INGRESS",
        trace_id="trc_01",
        parent_trace_id="trc_p01",
        original_trace_id=None,
        correlation_id=None,
        actor="usr_01",
        reason="test",
        payload_override=None,
        affected_records=50,
        status="IN_FLIGHT",
        error_message=None,
        created_at=now,
        completed_at=None,
    )

    domain = IpReplayLedgerRecord(
        id="rpl_01",
        tenant_id="tenant_01",
        idempotency_key="idem_01",
        target_type=ReplayTargetType.BATCH,
        target_id="target_01",
        target_stage=ReplayStage.STAGE_1_RAW_INGRESS,
        trace_id="trc_01",
        parent_trace_id="trc_p01",
        original_trace_id=None,
        correlation_id=None,
        actor="usr_01",
        reason="test",
        payload_override=None,
        affected_records=50,
        status=ReplayStatus.IN_FLIGHT,
        error_message=None,
        created_at=now,
        completed_at=None,
    )

    domain.mark_completed(affected_records=120)
    SqlAlchemyReplayLedgerRepository._update_orm_from_domain(orm, domain)

    assert orm.status == ReplayStatus.COMPLETED.value
    assert orm.affected_records == 120
    assert orm.completed_at is not None
    assert orm.error_message is None

    domain.mark_failed("Network failure")
    SqlAlchemyReplayLedgerRepository._update_orm_from_domain(orm, domain)

    assert orm.status == ReplayStatus.FAILED.value
    assert orm.error_message == "Network failure"


class _FakeResult:
    def __init__(self, item: object = None, items: list[object] | None = None) -> None:
        self._item = item
        self._items = items or []

    def scalar_one_or_none(self) -> object:
        return self._item

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[object]:
        return self._items


class _FakeAsyncSession:
    def __init__(self) -> None:
        self.info = {"session_type": "tenant"}
        self.added: list[object] = []
        self.flushed = False
        self.result = _FakeResult()

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        self.flushed = True

    async def execute(self, statement: object) -> _FakeResult:
        return self.result


@pytest.mark.asyncio
async def test_replay_ledger_repository_save_then_lookup() -> None:
    session = _FakeAsyncSession()

    repo = SqlAlchemyReplayLedgerRepository(cast(AsyncSession, session))

    record = IpReplayLedgerRecord.create(
        tenant_id="tenant_omega",
        idempotency_key="idem_omega_999",
        target_type=ReplayTargetType.BATCH,
        target_id="batch_999",
        target_stage=ReplayStage.STAGE_3_CANONICAL_MODEL,
        trace_id="trc_new",
        parent_trace_id="trc_parent",
        actor="system_replay",
        reason="Re-normalizing with updated algorithm",
        payload_override={"threshold": 0.95},
        affected_records=500,
    )

    # 1. Save (new record)
    session.result = _FakeResult(item=None)

    await repo.save(record)
    assert len(session.added) == 1
    assert session.flushed

    # 2. Get by ID
    orm_instance = SqlAlchemyReplayLedgerRepository._to_orm_model(record)
    session.result = _FakeResult(item=orm_instance)

    found = await repo.get_by_id(record.id, "tenant_omega")
    assert found is not None
    assert found.id == record.id
    assert found.target_stage == ReplayStage.STAGE_3_CANONICAL_MODEL
    assert found.idempotency_key == "idem_omega_999"

    # 3. Get by Idempotency Key
    idem_found = await repo.get_by_idempotency_key("tenant_omega", "idem_omega_999")
    assert idem_found is not None
    assert idem_found.id == record.id

    # 4. List by Target
    session.result = _FakeResult(items=[orm_instance])

    items = await repo.list_by_target("tenant_omega", ReplayTargetType.BATCH, "batch_999")
    assert len(items) == 1
    assert items[0].target_id == "batch_999"
    assert items[0].target_type == ReplayTargetType.BATCH
