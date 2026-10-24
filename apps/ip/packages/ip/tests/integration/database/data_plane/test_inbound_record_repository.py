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
from ip.engine.domain.enums import IpEventType, IpTraceEventType
from ip.engine.domain.models.inbound_record import InboundRecord
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_l1_inbound_record_repository_persists_record_trace_and_outbox(
    tenant_session: TenantSession,
) -> None:
    repo = SqlAlchemyInboundRecordRepository(tenant_session)
    tenant_id = "ten_dp_l1"
    trace_id = "ip_trc_l1_001"

    record = InboundRecord.create(
        tenant_id=tenant_id,
        connection_id="ip_conn_l1",
        app_id="itron_mdm",
        stream_name="meters",
        trace_id=trace_id,
        correlation_id="corr-l1-001",
        payload_bytes=b'{"meter_serial": "MTR-900"}',
        is_inlined=True,
        request_headers={"Content-Type": "application/json"},
        request_body={"meter_serial": "MTR-900"},
        response_status_code=202,
        response_headers={"X-Trace-ID": trace_id},
        response_body={"status": "ACCEPTED"},
        duration_ms=8,
    )
    await repo.save(record)

    fetched = await repo.get_by_id(record.id, tenant_id)
    assert fetched is not None
    assert fetched.id == record.id
    assert fetched.request_body == {"meter_serial": "MTR-900"}

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
    assert trace_rows[0].event_type == IpTraceEventType.L1_INGEST_RECEIVED.value

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
