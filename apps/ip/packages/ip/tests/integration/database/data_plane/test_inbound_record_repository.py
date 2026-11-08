"""Narrow Integration Tests for SqlAlchemyInboundRecordRepository against real PostgreSQL."""

from __future__ import annotations

import pytest
from database.types import TenantSession
from ip.engine.adapters.outbound.database.data_plane.inbound_record_repository import (
    SqlAlchemyInboundRecordRepository,
)
from ip.engine.adapters.outbound.database.models.data_plane import (
    IpDataPlaneOutboxRecord,
    IpTraceEventModel,
)
from ip.engine.domain.enums import IpEventType
from ip.engine.domain.replication.inbound_record import InboundBatchItemSpec, InboundRecord
from ip.engine.domain.trace.enums import IpTraceEventType
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_l1_inbound_record_repository_persists_record_with_trace_outbox(
    tenant_session: TenantSession,
) -> None:
    repo = SqlAlchemyInboundRecordRepository(tenant_session)
    tenant_id = "ten_dp_l1"
    trace_id = "ip_trc_l1_001"

    record = InboundRecord.create(
        tenant_id=tenant_id,
        connection_id="ip_conn_l1",
        app_id="acme_source",
        stream_name="records_alpha",
        trace_id=trace_id,
        correlation_id="corr-l1-001",
        payload_bytes=b'{"record_serial": "REC-900"}',
        is_inlined=True,
        request_headers={"Content-Type": "application/json"},
        request_body={"record_serial": "REC-900"},
        response_status_code=202,
        response_headers={"X-Trace-ID": trace_id},
        response_body={"status": "ACCEPTED"},
        duration_ms=8,
    )
    await repo.save(record)

    fetched = await repo.get_by_id(record.id, tenant_id)
    assert fetched is not None
    assert fetched.id == record.id
    assert fetched.request_body == {"record_serial": "REC-900"}

    by_trace = await repo.get_by_trace_id(trace_id, tenant_id)
    assert len(by_trace) == 1
    assert by_trace[0].id == record.id

    trace_rows = (
        (
            await tenant_session.execute(
                select(IpTraceEventModel).where(IpTraceEventModel.trace_id == trace_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(trace_rows) == 1
    assert trace_rows[0].event_type == IpTraceEventType.INGEST_RECEIVED.value

    outbox_rows = (
        (
            await tenant_session.execute(
                select(IpDataPlaneOutboxRecord).where(
                    IpDataPlaneOutboxRecord.tenant_id == tenant_id,
                    IpDataPlaneOutboxRecord.event_type == IpEventType.INBOUND_RECORD_CREATED.value,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(outbox_rows) == 1


@pytest.mark.asyncio
async def test_l1_inbound_record_repository_persists_range_batch_with_single_outbox_event(
    tenant_session: TenantSession,
) -> None:
    repo = SqlAlchemyInboundRecordRepository(tenant_session)
    tenant_id = "ten_dp_l1_range"
    trace_id = "ip_trc_l1_range_001"

    records = InboundRecord.create_range_batch(
        tenant_id=tenant_id,
        connection_id="ip_conn_l1_range",
        app_id="acme_source",
        stream_name="records_alpha",
        trace_id=trace_id,
        causation_depth=1,
        items=(
            InboundBatchItemSpec(
                payload_bytes=b'{"id": "rec_1"}',
                is_inlined=True,
                request_body={"id": "rec_1"},
            ),
            InboundBatchItemSpec(
                payload_bytes=b'{"id": "rec_2"}',
                is_inlined=True,
                request_body={"id": "rec_2"},
            ),
            InboundBatchItemSpec(
                payload_bytes=b'{"id": "rec_3"}',
                is_inlined=True,
                request_body={"id": "rec_3"},
            ),
        ),
    )
    await repo.save_batch(records)

    batch_id = records[0].batch_id or ""
    assert batch_id != ""

    fetched_slice = await repo.list_by_range(
        tenant_id,
        batch_id=batch_id,
        range_start=records[0].id,
        range_end=records[-1].id,
    )
    assert [r.id for r in fetched_slice] == [r.id for r in records]
    assert [r.batch_seq for r in fetched_slice] == [0, 1, 2]
    assert all(r.causation_depth == 1 for r in fetched_slice)

    outbox_rows = (
        (
            await tenant_session.execute(
                select(IpDataPlaneOutboxRecord).where(
                    IpDataPlaneOutboxRecord.tenant_id == tenant_id,
                    IpDataPlaneOutboxRecord.event_type == IpEventType.INBOUND_RECORD_CREATED.value,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(outbox_rows) == 1
    assert outbox_rows[0].payload["batch_id"] == batch_id
    assert outbox_rows[0].payload["range_start"] == records[0].id
    assert outbox_rows[0].payload["range_end"] == records[-1].id
    assert outbox_rows[0].payload["count"] == 3
    assert outbox_rows[0].payload["causation_depth"] == 1
