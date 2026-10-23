"""Pure zero-mock Data Mapper unit tests for SqlAlchemyOutboundRecordRepository."""

from __future__ import annotations

from ip.engine.adapters.outbound.database.data_plane.outbound_record_repository import (
    SqlAlchemyOutboundRecordRepository,
)
from ip.engine.domain.enums import OutboundDispatchStatus
from ip.engine.domain.models.outbound_record import OutboundRecord


def test_outbound_record_orm_and_domain_roundtrip_mapper() -> None:
    record = OutboundRecord.create_pending(
        tenant_id="tenant-123",
        connection_id="conn-456",
        app_id="salesforce",
        stream_name="orders",
        target_url="https://api.salesforce.com/orders",
        http_method="POST",
        payload_bytes=b'{"order_id": 99}',
        is_inlined=True,
        trace_id="trace-999",
        correlation_id="corr-999",
        request_headers={"Authorization": "Bearer token"},
        request_body={"order_id": 99},
    )
    record.mark_delivered(
        response_status_code=201,
        response_headers={"Location": "/orders/99"},
        response_body={"success": True},
        duration_ms=120,
    )

    orm = SqlAlchemyOutboundRecordRepository._to_orm_model(record)
    restored = SqlAlchemyOutboundRecordRepository._to_domain_model(orm)

    assert restored.id == record.id
    assert restored.status == OutboundDispatchStatus.DELIVERED
    assert restored.response_status_code == 201
    assert restored.duration_ms == 120
