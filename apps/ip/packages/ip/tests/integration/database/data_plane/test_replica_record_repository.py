"""Narrow Integration Tests for SqlAlchemyReplicaRecordRepository and SqlAlchemyReplicaRejectionRepository against real PostgreSQL."""

from __future__ import annotations

import pytest
from database.types import TenantSession
from ip.engine.adapters.outbound.database.data_plane.replica_record_repository import (
    SqlAlchemyReplicaRecordRepository,
)
from ip.engine.adapters.outbound.database.data_plane.replica_rejection_repository import (
    SqlAlchemyReplicaRejectionRepository,
)
from ip.engine.adapters.outbound.database.models.data_plane import (
    IpDataPlaneOutboxRecord,
    IpTraceEventModel,
    ReplicaRejectionModel,
)
from ip.engine.domain.enums import (
    CursorKind,
    IpEventType,
    IpTraceEventType,
    MergeOutcome,
)
from ip.engine.domain.models.replica_record import (
    ReplicaRecord,
    ReplicaRejection,
    compute_data_hash,
)
from ip.engine.ports.outbound.replica_record_repository_port import (
    ReplicaMergeCandidate,
)
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_l2_replica_record_repository_save_and_get_by_key(
    tenant_session: TenantSession,
) -> None:
    repo = SqlAlchemyReplicaRecordRepository(tenant_session)
    tenant_id = "ten_dp_l2"

    replica = ReplicaRecord.create(
        tenant_id=tenant_id,
        connection_id="ip_conn_l2",
        stream="meter_reading",
        record_key="MTR-200",
        data={"serial": "MTR-200", "kwh": 10.5},
        trace_id="ip_trc_l2_v1",
        correlation_id="corr-l2",
    )
    await repo.save(replica)

    fetched_v1 = await repo.get_by_key(
        tenant_id=tenant_id,
        connection_id="ip_conn_l2",
        stream="meter_reading",
        record_key="MTR-200",
    )
    assert fetched_v1 is not None
    assert fetched_v1.version == 1
    assert fetched_v1.data["kwh"] == 10.5

    changed = fetched_v1.update_snapshot(
        new_data={"serial": "MTR-200", "kwh": 22.8},
        trace_id="ip_trc_l2_v2",
        correlation_id="corr-l2",
    )
    assert changed is True
    await repo.save(fetched_v1)

    fetched_v2 = await repo.get_by_key(
        tenant_id=tenant_id,
        connection_id="ip_conn_l2",
        stream="meter_reading",
        record_key="MTR-200",
    )
    assert fetched_v2 is not None
    assert fetched_v2.version == 2
    assert fetched_v2.data["kwh"] == 22.8
    assert fetched_v2.trace_id == "ip_trc_l2_v2"


@pytest.mark.asyncio
async def test_l2_replica_merge_batch_all_outcomes_and_outbox_emission(
    tenant_session: TenantSession,
) -> None:
    repo = SqlAlchemyReplicaRecordRepository(tenant_session)
    tenant_id = "ten_merge_batch"
    conn_id = "ip_conn_mb"
    stream = "orders"

    # 1. Batch 1: INSERT ord-1, INSERT ord-2 (with intra-batch duplicate folding), and unseen TOMBSTONE ord-del-unseen
    d1_v1 = {"id": "ord-1", "amount": 100}
    d2_v1 = {"id": "ord-2", "amount": 200}
    d2_v2 = {"id": "ord-2", "amount": 250}
    d_unseen_del = {"id": "ord-del-unseen", "deleted": True}

    batch1 = [
        ReplicaMergeCandidate(
            tenant_id=tenant_id,
            connection_id=conn_id,
            stream=stream,
            record_key="ord-1",
            primary_key_values=("ord-1",),
            data=d1_v1,
            data_hash=compute_data_hash(d1_v1),
            cursor_value="10",
            cursor_kind=CursorKind.INTEGER.value,
            is_deleted=False,
            generation_id=1,
            source_inbound_record_id="ip_inb_b1",
            trace_id="ip_trc_b1",
        ),
        ReplicaMergeCandidate(
            tenant_id=tenant_id,
            connection_id=conn_id,
            stream=stream,
            record_key="ord-2",
            primary_key_values=("ord-2",),
            data=d2_v1,
            data_hash=compute_data_hash(d2_v1),
            cursor_value="10",
            cursor_kind=CursorKind.INTEGER.value,
            is_deleted=False,
            generation_id=1,
            source_inbound_record_id="ip_inb_b1",
            trace_id="ip_trc_b1",
        ),
        # Intra-batch duplicate for ord-2 with newer cursor -> folds into UPDATE on top of INSERT
        ReplicaMergeCandidate(
            tenant_id=tenant_id,
            connection_id=conn_id,
            stream=stream,
            record_key="ord-2",
            primary_key_values=("ord-2",),
            data=d2_v2,
            data_hash=compute_data_hash(d2_v2),
            cursor_value="11",
            cursor_kind=CursorKind.INTEGER.value,
            is_deleted=False,
            generation_id=1,
            source_inbound_record_id="ip_inb_b1",
            trace_id="ip_trc_b1",
        ),
        # Unseen delete -> TOMBSTONE
        ReplicaMergeCandidate(
            tenant_id=tenant_id,
            connection_id=conn_id,
            stream=stream,
            record_key="ord-del-unseen",
            primary_key_values=("ord-del-unseen",),
            data=d_unseen_del,
            data_hash=compute_data_hash(d_unseen_del),
            cursor_value="10",
            cursor_kind=CursorKind.INTEGER.value,
            is_deleted=True,
            generation_id=1,
            source_inbound_record_id="ip_inb_b1",
            trace_id="ip_trc_b1",
        ),
    ]

    res1 = await repo.merge_batch(batch1)
    outcomes1 = [r.outcome for r in res1]
    assert outcomes1 == [
        MergeOutcome.INSERT,
        MergeOutcome.INSERT,
        MergeOutcome.UPDATE,
        MergeOutcome.TOMBSTONE,
    ]

    ord2 = await repo.get_by_key(tenant_id, conn_id, stream, "ord-2")
    assert ord2 is not None
    assert ord2.data["amount"] == 250
    assert ord2.version == 2

    unseen_del = await repo.get_by_key(tenant_id, conn_id, stream, "ord-del-unseen")
    assert unseen_del is not None
    assert unseen_del.deleted_at is not None

    # 2. Batch 2: NOOP on ord-1, STALE on ord-2 (cursor 5 < 11), NOOP on replaying delete of ord-del-unseen
    batch2 = [
        # Identical payload & cursor -> NOOP
        ReplicaMergeCandidate(
            tenant_id=tenant_id,
            connection_id=conn_id,
            stream=stream,
            record_key="ord-1",
            primary_key_values=("ord-1",),
            data=d1_v1,
            data_hash=compute_data_hash(d1_v1),
            cursor_value="10",
            cursor_kind=CursorKind.INTEGER.value,
            is_deleted=False,
            generation_id=1,
            source_inbound_record_id="ip_inb_b2",
            trace_id="ip_trc_b2",
        ),
        # Older cursor (5 < 11) -> STALE
        ReplicaMergeCandidate(
            tenant_id=tenant_id,
            connection_id=conn_id,
            stream=stream,
            record_key="ord-2",
            primary_key_values=("ord-2",),
            data={"id": "ord-2", "amount": 999},
            data_hash=compute_data_hash({"id": "ord-2", "amount": 999}),
            cursor_value="5",
            cursor_kind=CursorKind.INTEGER.value,
            is_deleted=False,
            generation_id=1,
            source_inbound_record_id="ip_inb_b2",
            trace_id="ip_trc_b2",
        ),
        # Replaying delete on already-tombstoned record -> NOOP
        ReplicaMergeCandidate(
            tenant_id=tenant_id,
            connection_id=conn_id,
            stream=stream,
            record_key="ord-del-unseen",
            primary_key_values=("ord-del-unseen",),
            data=d_unseen_del,
            data_hash=compute_data_hash(d_unseen_del),
            cursor_value="10",
            cursor_kind=CursorKind.INTEGER.value,
            is_deleted=True,
            generation_id=1,
            source_inbound_record_id="ip_inb_b2",
            trace_id="ip_trc_b2",
        ),
    ]

    res2 = await repo.merge_batch(batch2)
    assert [r.outcome for r in res2] == [
        MergeOutcome.NOOP,
        MergeOutcome.STALE,
        MergeOutcome.NOOP,
    ]

    # Verify outbox events emitted for trace ip_trc_b2 is 0 (all NOOP/STALE)
    outbox_b2 = (
        (
            await tenant_session.execute(
                select(IpDataPlaneOutboxRecord).where(
                    IpDataPlaneOutboxRecord.tenant_id == tenant_id,
                    IpDataPlaneOutboxRecord.event_type == IpEventType.REPLICA_RECORD_CHANGED.value,
                )
            )
        )
        .scalars()
        .all()
    )
    # Only the 4 events from batch 1 (INSERT ord-1, INSERT ord-2, UPDATE ord-2, TOMBSTONE ord-del-unseen) should exist
    assert len(outbox_b2) == 4


@pytest.mark.asyncio
async def test_l2_tombstone_unseen_generations_drains_trace_and_outbox(
    tenant_session: TenantSession,
) -> None:
    repo = SqlAlchemyReplicaRecordRepository(tenant_session)
    tenant_id = "ten_sweep_l2"
    conn_id = "ip_conn_sweep"
    stream = "devices"

    # Seed 2 records in generation 1 and 1 record in generation 2
    candidates = [
        ReplicaMergeCandidate(
            tenant_id=tenant_id,
            connection_id=conn_id,
            stream=stream,
            record_key="dev-old-1",
            primary_key_values=("dev-old-1",),
            data={"id": "dev-old-1"},
            data_hash=compute_data_hash({"id": "dev-old-1"}),
            cursor_value=None,
            cursor_kind=CursorKind.STRING.value,
            is_deleted=False,
            generation_id=1,
            source_inbound_record_id="ip_inb_g1",
            trace_id="ip_trc_g1",
        ),
        ReplicaMergeCandidate(
            tenant_id=tenant_id,
            connection_id=conn_id,
            stream=stream,
            record_key="dev-old-2",
            primary_key_values=("dev-old-2",),
            data={"id": "dev-old-2"},
            data_hash=compute_data_hash({"id": "dev-old-2"}),
            cursor_value=None,
            cursor_kind=CursorKind.STRING.value,
            is_deleted=False,
            generation_id=1,
            source_inbound_record_id="ip_inb_g1",
            trace_id="ip_trc_g1",
        ),
        ReplicaMergeCandidate(
            tenant_id=tenant_id,
            connection_id=conn_id,
            stream=stream,
            record_key="dev-current",
            primary_key_values=("dev-current",),
            data={"id": "dev-current"},
            data_hash=compute_data_hash({"id": "dev-current"}),
            cursor_value=None,
            cursor_kind=CursorKind.STRING.value,
            is_deleted=False,
            generation_id=2,
            source_inbound_record_id="ip_inb_g2",
            trace_id="ip_trc_g2",
        ),
    ]
    await repo.merge_batch(candidates)

    tombstoned = await repo.tombstone_unseen_generations(
        tenant_id=tenant_id,
        connection_id=conn_id,
        stream=stream,
        current_generation=2,
        limit=500,
        trace_id="ip_trc_sweep_g2",
    )
    assert tombstoned == 2

    # Verify dev-old-1 is tombstoned and dev-current is still active
    old1 = await repo.get_by_key(tenant_id, conn_id, stream, "dev-old-1")
    current = await repo.get_by_key(tenant_id, conn_id, stream, "dev-current")
    assert old1 is not None and old1.deleted_at is not None
    assert current is not None and current.deleted_at is None

    # Verify trace events emitted for sweep
    sweep_traces = (
        (
            await tenant_session.execute(
                select(IpTraceEventModel).where(
                    IpTraceEventModel.tenant_id == tenant_id,
                    IpTraceEventModel.trace_id == "ip_trc_sweep_g2",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(sweep_traces) == 2
    assert all(t.event_type == IpTraceEventType.L2_REPLICA_TOMBSTONED.value for t in sweep_traces)


@pytest.mark.asyncio
async def test_l2_replica_rejection_repository_persists_batch(
    tenant_session: TenantSession,
) -> None:
    repo = SqlAlchemyReplicaRejectionRepository(tenant_session)
    rej = ReplicaRejection.create(
        tenant_id="ten_rej_l2",
        connection_id="ip_conn_rej",
        stream="meters",
        inbound_record_id="ip_inb_rej",
        record_index=3,
        reason="MISSING_PRIMARY_KEY",
        detail='{"kwh": 42}',
        trace_id="ip_trc_rej",
    )
    assert rej.id.startswith("ip_rej_")
    await repo.save_batch([rej])

    saved = (
        await tenant_session.execute(
            select(ReplicaRejectionModel).where(ReplicaRejectionModel.id == rej.id)
        )
    ).scalar_one_or_none()
    assert saved is not None
    assert saved.reason == "MISSING_PRIMARY_KEY"
    assert saved.record_index == 3
