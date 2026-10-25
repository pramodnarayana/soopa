"""Pure zero-mock Data Mapper unit tests for SqlAlchemyInboundRecordRepository."""

from __future__ import annotations

from ip.engine.adapters.outbound.database.data_plane.inbound_record_repository import (
    SqlAlchemyInboundRecordRepository,
)
from ip.engine.domain.models.inbound_record import InboundRecord


def test_inbound_record_orm_and_domain_roundtrip_mapper() -> None:
    record = InboundRecord.create(
        tenant_id="tenant-123",
        connection_id="conn-456",
        app_id="salesforce",
        stream_name="contacts",
        trace_id="trace-789",
        correlation_id="corr-111",
        payload_bytes=b'{"id": "1"}',
        is_inlined=True,
        request_headers={"Content-Type": "application/json"},
        request_body={"id": "1"},
        response_status_code=200,
        response_headers={"X-Status": "ok"},
        response_body={"success": True},
        duration_ms=45,
    )

    orm = SqlAlchemyInboundRecordRepository._to_orm_model(record)
    restored = SqlAlchemyInboundRecordRepository._to_domain_model(orm)

    assert restored.id == record.id
    assert restored.tenant_id == "tenant-123"
    assert restored.trace_id == "trace-789"
    assert restored.correlation_id == "corr-111"
    assert restored.request_body == {"id": "1"}
    assert restored.response_body == {"success": True}
    assert restored.duration_ms == 45
