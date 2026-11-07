"""Narrow Integration Tests for SqlAlchemyOutboundRecordRepository against real PostgreSQL."""

from __future__ import annotations

import pytest
from database.types import TenantSession
from ip.engine.adapters.outbound.database.data_plane.outbound_record_repository import (
    SqlAlchemyOutboundRecordRepository,
)
from ip.engine.domain.dispatch.enums import OutboundDispatchStatus
from ip.engine.domain.dispatch.outbound_record import OutboundRecord

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
        stream_name="partner_events",
        target_url="https://acme.my.salesforce.com/services/data/v60.0/sobjects/Partner_Event__c",
        http_method="POST",
        payload_bytes=b'{"Record__c":"REC-500","Quantity__c":18.4}',
        is_inlined=True,
        trace_id=trace_id,
        correlation_id="corr-l5-001",
        request_headers={"Content-Type": "application/json"},
        request_body={"Record__c": "REC-500", "Quantity__c": 18.4},
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


@pytest.mark.asyncio
async def test_l5_outbound_record_repository_persists_idempotency_key_with_redacted_headers(
    tenant_session: TenantSession,
) -> None:
    repo = SqlAlchemyOutboundRecordRepository(tenant_session)
    tenant_id = "ten_dp_l5_idem"
    conn_id = "ip_conn_erp"

    outbound = OutboundRecord.create_pending(
        tenant_id=tenant_id,
        connection_id=conn_id,
        app_id="partner_erp",
        stream_name="records_alpha",
        operation="UPSERT",
        idempotency_key="idem_erp_rec_900",
        external_record_id="REC-900",
        target_url="https://erp.partner.local/api/records",
        http_method="PUT",
        payload_bytes=b'{"record_id":"REC-900","quantity":44.1}',
        is_inlined=True,
        trace_id="ip_trc_l5_idem_1",
        correlation_id="REC-900",
        request_headers={
            "Authorization": "Bearer secret_erp_token",
            "Idempotency-Key": "idem_erp_rec_900",
        },
        request_body={"record_id": "REC-900", "quantity": 44.1},
    )
    outbound.schedule_retry(
        error_message="HTTP 429 Rate Limit",
        next_attempt=2,
        response_status_code=429,
        failure_category="RATE_LIMITED",
        retry_after_seconds=30,
    )
    await repo.save(outbound)

    looked_up = await repo.get_by_idempotency_key(
        tenant_id=tenant_id,
        connection_id=conn_id,
        idempotency_key="idem_erp_rec_900",
    )
    assert looked_up is not None
    assert looked_up.id == outbound.id
    assert looked_up.operation == "UPSERT"
    assert looked_up.external_record_id == "REC-900"
    assert looked_up.status == OutboundDispatchStatus.RETRY_SCHEDULED
    assert looked_up.failure_category == "RATE_LIMITED"
    assert looked_up.retry_after_seconds == 30
    assert looked_up.request_headers["Authorization"] == "***REDACTED***"
