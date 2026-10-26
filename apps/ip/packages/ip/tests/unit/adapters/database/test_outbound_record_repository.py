"""Pure zero-mock Data Mapper unit tests for SqlAlchemyOutboundRecordRepository."""

from __future__ import annotations

from ip.engine.adapters.outbound.database.data_plane.outbound_record_repository import (
    SqlAlchemyOutboundRecordRepository,
)
from ip.engine.domain.enums import (
    HttpWriteOperation,
    OutboundDispatchStatus,
    OutboundFailureCategory,
)
from ip.engine.domain.models.outbound_record import OutboundRecord


def test_outbound_record_orm_and_domain_roundtrip_mapper() -> None:
    record = OutboundRecord.create_pending(
        tenant_id="tenant-123",
        connection_id="conn-456",
        app_id="salesforce",
        stream_name="orders",
        operation=HttpWriteOperation.UPSERT.value,
        target_url="https://api.salesforce.com/orders/ext-99",
        http_method="PUT",
        payload_bytes=b'{"order_id": 99}',
        is_inlined=True,
        trace_id="trace-999",
        correlation_id="corr-999",
        idempotency_key="idem-orders-99",
        external_record_id="ext-99",
        request_headers={"Authorization": "[REDACTED]", "Idempotency-Key": "idem-orders-99"},
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
    assert restored.operation == HttpWriteOperation.UPSERT.value
    assert restored.idempotency_key == "idem-orders-99"
    assert restored.external_record_id == "ext-99"
    assert restored.response_status_code == 201
    assert restored.duration_ms == 120


def test_outbound_record_mapper_preserves_retry_and_failure_metadata() -> None:
    record = OutboundRecord.create_pending(
        tenant_id="tenant-123",
        connection_id="conn-456",
        app_id="salesforce",
        stream_name="orders",
        operation=HttpWriteOperation.CREATE.value,
        target_url="https://api.salesforce.com/orders",
        http_method="POST",
        payload_bytes=b'{"order_id": 100}',
        is_inlined=True,
        trace_id="trace-100",
        correlation_id="corr-100",
        idempotency_key="idem-orders-100",
    )

    record.schedule_retry(
        next_attempt=2,
        error_message="429 Too Many Requests",
        failure_category=OutboundFailureCategory.RATE_LIMITED.value,
        retry_after_seconds=45,
        response_status_code=429,
        response_headers={"Retry-After": "45"},
        response_body={"error": "rate_limit_exceeded"},
        duration_ms=85,
    )

    orm = SqlAlchemyOutboundRecordRepository._to_orm_model(record)
    restored = SqlAlchemyOutboundRecordRepository._to_domain_model(orm)

    assert restored.status == OutboundDispatchStatus.RETRY_SCHEDULED
    assert restored.failure_category == OutboundFailureCategory.RATE_LIMITED.value
    assert restored.retry_after_seconds == 45
    assert restored.attempt_number == 2
    assert restored.response_status_code == 429
    assert restored.error_message == "429 Too Many Requests"
