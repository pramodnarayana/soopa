"""Narrow Integration Tests for SqlAlchemyOutboundRecordRepository against real PostgreSQL."""

from __future__ import annotations

import pytest
from database.types import TenantSession
from ip.engine.adapters.outbound.database.data_plane.outbound_record_repository import (
    SqlAlchemyOutboundRecordRepository,
)
from ip.engine.domain.enums import OutboundDispatchStatus
from ip.engine.domain.models.outbound_record import OutboundRecord

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_l5_outbound_record_repository_lifecycle_transitions(
    tenant_session: TenantSession,
) -> None:
    repo = SqlAlchemyOutboundRecordRepository(tenant_session)
    tenant_id = "ten_dp_l5"
    trace_id = "ip_trc_l5_001"

    outbound = OutboundRecord.create_pending(
        tenant_id=tenant_id,
        connection_id="ip_conn_sf",
        app_id="salesforce",
        stream_name="meter_events",
        target_url="https://acme.my.salesforce.com/services/data/v60.0/sobjects/Meter_Event__c",
        http_method="POST",
        payload_bytes=b'{"Meter__c":"MTR-500","kWh__c":18.4}',
        is_inlined=True,
        trace_id=trace_id,
        correlation_id="corr-l5-001",
        request_headers={"Content-Type": "application/json"},
        request_body={"Meter__c": "MTR-500", "kWh__c": 18.4},
    )
    await repo.save(outbound)

    pending = await repo.get_by_id(outbound.id, tenant_id)
    assert pending is not None
    assert pending.status == OutboundDispatchStatus.PENDING

    pending.mark_delivered(
        response_status_code=201,
        response_headers={"X-SFDC-Request-Id": "req-123"},
        response_body={"id": "a01xx000003DGbYAAW", "success": True},
        duration_ms=95,
    )
    await repo.save(pending)

    delivered = await repo.get_by_id(outbound.id, tenant_id)
    assert delivered is not None
    assert delivered.status == OutboundDispatchStatus.DELIVERED
    assert delivered.response_status_code == 201
    assert delivered.duration_ms == 95
