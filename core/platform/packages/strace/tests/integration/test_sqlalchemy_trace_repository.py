"""Narrow integration tests for SqlAlchemyTraceRepository against real PostgreSQL with SAVEPOINT rollback."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from database.provider import get_async_engine
from dotenv import load_dotenv
from sqlalchemy import DateTime, String
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from strace.adapters import (
    SqlAlchemyTraceRepository,
    TenantTraceableOrmModel,
    TenantTraceLineageOrmModel,
    TraceEventMixin,
    TraceEventSpec,
    TraceStageSpec,
    TraceStageSpecPort,
)
from strace.domain import (
    TraceEvent,
    TraceEventType,
    TraceStageAttemptRow,
    TraceStatus,
)

load_dotenv()

pytestmark = pytest.mark.integration


class _TraceIntegrationBase(DeclarativeBase):
    pass


class _Stage1Orm(_TraceIntegrationBase, TenantTraceableOrmModel):
    __tablename__ = "trace_pkg_int_stage_1"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class _Stage2Orm(_TraceIntegrationBase, TenantTraceLineageOrmModel):
    __tablename__ = "trace_pkg_int_stage_2"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class _TraceEventOrm(_TraceIntegrationBase, TraceEventMixin):
    __tablename__ = "trace_pkg_int_events"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


def _to_domain_event(orm: _TraceEventOrm) -> TraceEvent:
    return TraceEvent(
        id=orm.id,
        tenant_id=orm.tenant_id,
        trace_id=orm.trace_id,
        correlation_id=orm.correlation_id,
        event_type=orm.event_type,
        actor=orm.actor,
        metadata=dict(orm.metadata_) if orm.metadata_ is not None else None,
        created_at=orm.created_at,
    )


def _to_orm_event(event: TraceEvent) -> _TraceEventOrm:
    return _TraceEventOrm(
        id=event.id,
        tenant_id=event.tenant_id,
        trace_id=event.trace_id,
        correlation_id=event.correlation_id,
        event_type=event.event_type,
        actor=event.actor,
        metadata_=dict(event.metadata) if event.metadata is not None else None,
        created_at=event.created_at,
    )


_EVENT_SPEC: TraceEventSpec[_TraceEventOrm] = TraceEventSpec(
    model_cls=_TraceEventOrm,
    to_domain_fn=_to_domain_event,
    to_orm_fn=_to_orm_event,
)

_STAGE_SPECS: tuple[TraceStageSpecPort, ...] = (
    TraceStageSpec(
        model_cls=_Stage1Orm,
        timestamp_col=_Stage1Orm.created_at,
        status_col=_Stage1Orm.status,
        correlation_cols=(_Stage1Orm.correlation_id,),
        to_attempt_row=lambda r: TraceStageAttemptRow(
            trace_id=r.trace_id,
            correlation_id=r.correlation_id,
            status=r.status,
            primary_layer="STAGE_1",
            created_at=r.created_at,
            replay_count=r.replay_count,
            parent_trace_id=r.parent_trace_id,
            original_trace_id=r.original_trace_id,
        ),
    ),
    TraceStageSpec(
        model_cls=_Stage2Orm,
        timestamp_col=_Stage2Orm.created_at,
        status_col=_Stage2Orm.status,
        to_attempt_row=lambda r: TraceStageAttemptRow(
            trace_id=r.trace_id,
            correlation_id=None,
            status=r.status,
            primary_layer="STAGE_2",
            created_at=r.created_at,
            replay_count=r.replay_count,
            parent_trace_id=r.parent_trace_id,
            original_trace_id=r.original_trace_id,
        ),
    ),
)


def _get_test_db_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ucp_admin:ucp_password@localhost:5432/global_db",
    )


@pytest_asyncio.fixture(scope="function")
async def pg_engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = get_async_engine(_get_test_db_url())
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def pg_connection(pg_engine: AsyncEngine) -> AsyncGenerator[AsyncConnection, None]:
    connection = await pg_engine.connect()
    transaction = await connection.begin()
    try:
        await connection.run_sync(_TraceIntegrationBase.metadata.create_all)
        yield connection
    finally:
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture(scope="function")
async def pg_session(pg_connection: AsyncConnection) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(
        bind=pg_connection,
        expire_on_commit=False,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
    )
    async with session_factory() as session:
        yield session


@pytest.mark.asyncio
async def test_sqlalchemy_trace_repository_events_lineage_and_correlation_round_trip(
    pg_session: AsyncSession,
) -> None:
    repo = SqlAlchemyTraceRepository(
        pg_session,
        event_spec=_EVENT_SPEC,
        stage_specs=_STAGE_SPECS,
    )
    tenant_id = f"ten_{os.urandom(12).hex()}"
    other_tenant_id = f"ten_{os.urandom(12).hex()}"
    root_trace_id = f"trc_{os.urandom(12).hex()}"
    child_trace_id = f"trc_{os.urandom(12).hex()}"
    nonexistent_trace_id = f"trc_{os.urandom(12).hex()}"
    evt_1_id = f"evt_{os.urandom(12).hex()}"
    evt_2_id = f"evt_{os.urandom(12).hex()}"
    evt_other_id = f"evt_{os.urandom(12).hex()}"
    s1_root_id = f"s1_{os.urandom(12).hex()}"
    s2_root_id = f"s2_{os.urandom(12).hex()}"
    s2_child_id = f"s2_{os.urandom(12).hex()}"
    t0 = datetime.now(UTC)
    t1 = t0 + timedelta(seconds=5)
    t2 = t0 + timedelta(seconds=10)

    # 1. Save single and batch trace events and verify chronological listing + tenant isolation
    evt_1 = TraceEvent(
        id=evt_1_id,
        tenant_id=tenant_id,
        trace_id=root_trace_id,
        correlation_id="ORD-777",
        event_type=TraceEventType.RECEIVED,
        actor="GATEWAY",
        metadata={"step": 1},
        created_at=t0,
    )
    evt_2 = TraceEvent(
        id=evt_2_id,
        tenant_id=tenant_id,
        trace_id=root_trace_id,
        correlation_id="ORD-777",
        event_type=TraceEventType.DELIVERY_FAILED,
        actor="WORKER",
        metadata={"step": 2, "status_code": 502},
        created_at=t1,
    )
    evt_other_tenant = TraceEvent(
        id=evt_other_id,
        tenant_id=other_tenant_id,
        trace_id=root_trace_id,
        correlation_id="ORD-777",
        event_type=TraceEventType.RECEIVED,
        actor="GATEWAY",
        created_at=t0,
    )
    await repo.save_trace_event(evt_2)
    await repo.save_all_trace_events([evt_1, evt_other_tenant])
    await repo.save_all_trace_events([])

    events = await repo.list_trace_events(tenant_id, root_trace_id)
    assert [e.id for e in events] == [evt_1_id, evt_2_id]
    assert events[0].correlation_id == "ORD-777"
    assert events[1].metadata == {"step": 2, "status_code": 502}

    # 2. Seed stage 1 and stage 2 rows for root attempt and delivery-retry child attempt
    pg_session.add_all(
        [
            _Stage1Orm(
                id=s1_root_id,
                tenant_id=tenant_id,
                trace_id=root_trace_id,
                correlation_id="ORD-777",
                parent_trace_id=None,
                original_trace_id=root_trace_id,
                replay_count=0,
                status=TraceStatus.INGESTED.value,
                created_at=t0,
            ),
            _Stage2Orm(
                id=s2_root_id,
                tenant_id=tenant_id,
                trace_id=root_trace_id,
                parent_trace_id=None,
                original_trace_id=root_trace_id,
                replay_count=0,
                status=TraceStatus.FAILED.value,
                created_at=t1,
            ),
            _Stage2Orm(
                id=s2_child_id,
                tenant_id=tenant_id,
                trace_id=child_trace_id,
                parent_trace_id=root_trace_id,
                original_trace_id=root_trace_id,
                replay_count=1,
                status=TraceStatus.DELIVERED.value,
                created_at=t2,
            ),
        ]
    )
    await pg_session.flush()

    # 3. Verify root trace resolution from child_trace_id and unknown trace_id
    resolved_root = await repo.resolve_root_trace_id(tenant_id, child_trace_id)
    assert resolved_root == root_trace_id
    assert await repo.resolve_root_trace_id(tenant_id, nonexistent_trace_id) == nonexistent_trace_id

    # 4. Verify fetch_lineage_family_rows returns both root and child stage 2 rows
    family_rows = await repo.fetch_lineage_family_rows(
        _Stage2Orm,
        tenant_id=tenant_id,
        root_trace_id=root_trace_id,
        order_by_col=_Stage2Orm.created_at.asc(),
    )
    assert [r.id for r in family_rows] == [s2_root_id, s2_child_id]

    # 5. Verify get_trace_lineage merges Stage 1 -> Stage 2 and sorts by (replay_count, created_at)
    lineage = await repo.get_trace_lineage(tenant_id, child_trace_id)
    assert len(lineage) == 2
    assert lineage[0].trace_id == root_trace_id
    assert lineage[0].correlation_id == "ORD-777"
    assert lineage[0].status == TraceStatus.FAILED.value
    assert lineage[0].primary_layer == "STAGE_2"
    assert lineage[0].replay_count == 0
    assert lineage[1].trace_id == child_trace_id
    assert lineage[1].status == TraceStatus.DELIVERED.value
    assert lineage[1].primary_layer == "STAGE_2"
    assert lineage[1].replay_count == 1
    assert lineage[1].parent_trace_id == root_trace_id
    assert lineage[1].original_trace_id == root_trace_id

    # 6. Verify find_traces_by_correlation_id
    corr_matches = await repo.find_traces_by_correlation_id(tenant_id, "ORD-777", limit=10)
    assert len(corr_matches) == 1
    assert corr_matches[0].trace_id == root_trace_id
    assert corr_matches[0].correlation_id == "ORD-777"

    # 7. Verify list_recent_traces orders newest traces first, deduplicates stages, and isolates tenant
    later_trace_id = f"trc_{os.urandom(12).hex()}"
    t3 = t0 + timedelta(seconds=20)
    pg_session.add_all(
        [
            _Stage1Orm(
                id=f"s1_{os.urandom(12).hex()}",
                tenant_id=tenant_id,
                trace_id=later_trace_id,
                correlation_id="ORD-888",
                parent_trace_id=None,
                original_trace_id=later_trace_id,
                replay_count=0,
                status=TraceStatus.INGESTED.value,
                created_at=t3,
            ),
            _Stage1Orm(
                id=f"s1_{os.urandom(12).hex()}",
                tenant_id=other_tenant_id,
                trace_id=f"trc_{os.urandom(12).hex()}",
                correlation_id="ORD-999",
                parent_trace_id=None,
                original_trace_id=None,
                replay_count=0,
                status=TraceStatus.INGESTED.value,
                created_at=t3 + timedelta(seconds=5),
            ),
        ]
    )
    await pg_session.flush()

    recent_items = await repo.list_recent_traces(tenant_id, limit=10)
    assert [item.trace_id for item in recent_items] == [
        later_trace_id,
        child_trace_id,
        root_trace_id,
    ]
    assert recent_items[0].correlation_id == "ORD-888"
    assert recent_items[0].primary_layer == "STAGE_1"
    assert recent_items[1].primary_layer == "STAGE_2"
    assert recent_items[1].replay_count == 1
    assert recent_items[2].primary_layer == "STAGE_2"
    assert recent_items[2].status == TraceStatus.FAILED.value

    limited_items = await repo.list_recent_traces(tenant_id, limit=2)
    assert [item.trace_id for item in limited_items] == [later_trace_id, child_trace_id]

    # 8. Verify SQL pushdown for status & min_replay_count never starves older FAILED/INGESTED rows across >300 newer DELIVERED rows
    bulk_rows: list[_Stage1Orm | _Stage2Orm] = []
    for idx in range(320):
        bulk_trc_id = f"trc_{os.urandom(12).hex()}"
        bulk_ts = t3 + timedelta(minutes=idx + 1)
        bulk_rows.append(
            _Stage1Orm(
                id=f"s1_{os.urandom(12).hex()}",
                tenant_id=tenant_id,
                trace_id=bulk_trc_id,
                correlation_id=f"ORD-BULK-{idx}",
                parent_trace_id=None,
                original_trace_id=bulk_trc_id,
                replay_count=0,
                status=TraceStatus.INGESTED.value,
                created_at=bulk_ts,
            )
        )
        bulk_rows.append(
            _Stage2Orm(
                id=f"s2_{os.urandom(12).hex()}",
                tenant_id=tenant_id,
                trace_id=bulk_trc_id,
                parent_trace_id=None,
                original_trace_id=bulk_trc_id,
                replay_count=0,
                status=TraceStatus.DELIVERED.value,
                created_at=bulk_ts + timedelta(seconds=1),
            )
        )
    pg_session.add_all(bulk_rows)
    await pg_session.flush()

    failed_items = await repo.list_recent_traces(
        tenant_id,
        status=TraceStatus.FAILED,
        limit=10,
    )
    assert [item.trace_id for item in failed_items] == [root_trace_id]
    assert failed_items[0].correlation_id == "ORD-777"
    assert failed_items[0].primary_layer == "STAGE_2"

    ingested_only_items = await repo.list_recent_traces(
        tenant_id,
        status=TraceStatus.INGESTED,
        limit=10,
    )
    assert [item.trace_id for item in ingested_only_items] == [later_trace_id]
    assert ingested_only_items[0].primary_layer == "STAGE_1"

    replayed_items = await repo.list_recent_traces(
        tenant_id,
        min_replay_count=1,
        limit=10,
    )
    assert [item.trace_id for item in replayed_items] == [child_trace_id]
    assert replayed_items[0].replay_count == 1


@pytest.mark.asyncio
async def test_sqlalchemy_trace_repository_without_specs_returns_empty_and_noops(
    pg_session: AsyncSession,
) -> None:
    empty_repo = SqlAlchemyTraceRepository(pg_session)
    empty_tenant_id = f"ten_{os.urandom(12).hex()}"
    empty_trace_id = f"trc_{os.urandom(12).hex()}"
    evt = TraceEvent(
        id=f"evt_{os.urandom(12).hex()}",
        tenant_id=empty_tenant_id,
        trace_id=empty_trace_id,
        event_type=TraceEventType.RECEIVED,
        actor="SYSTEM",
    )
    await empty_repo.save_trace_event(evt)
    await empty_repo.save_all_trace_events([evt])
    assert await empty_repo.list_trace_events(empty_tenant_id, empty_trace_id) == []
    assert await empty_repo.get_trace_lineage(empty_tenant_id, empty_trace_id) == []
    assert await empty_repo.find_traces_by_correlation_id(empty_tenant_id, "CORR-1") == []
    assert await empty_repo.list_recent_traces(empty_tenant_id, limit=10) == []
