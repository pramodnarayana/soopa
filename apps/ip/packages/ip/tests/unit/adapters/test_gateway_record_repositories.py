"""Unit tests for SqlAlchemyInboundRecordRepository and SqlAlchemyOutboundRecordRepository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from ip.adapters.outbound.database.inbound_record_repository import (
    SqlAlchemyInboundRecordRepository,
)
from ip.adapters.outbound.database.models.inbound_record_model import InboundRecordModel
from ip.adapters.outbound.database.models.outbound_record_model import OutboundRecordModel
from ip.adapters.outbound.database.models.outbox_model import IpOutboxRecord
from ip.adapters.outbound.database.outbound_record_repository import (
    SqlAlchemyOutboundRecordRepository,
)
from ip.domain.enums import OutboundDispatchStatus
from ip.domain.models.inbound_record import InboundRecord
from ip.domain.models.outbound_record import OutboundRecord
from sqlalchemy.ext.asyncio import AsyncSession


class FakeScalarResult:
    def __init__(self, item: Any) -> None:
        self._item = item

    def scalar_one_or_none(self) -> Any:
        return self._item

    def scalars(self) -> FakeScalarResult:
        return self

    def all(self) -> list[Any]:
        if isinstance(self._item, list):
            return self._item
        return [self._item] if self._item is not None else []


class FakeAsyncSession:
    def __init__(self, query_result: Any = None) -> None:
        self.query_result = query_result
        self.added_records: list[Any] = []
        self.flushed = False
        self.executed_statements: list[Any] = []

    async def execute(self, statement: Any) -> FakeScalarResult:
        self.executed_statements.append(statement)
        return FakeScalarResult(self.query_result)

    def add(self, instance: Any) -> None:
        self.added_records.append(instance)

    async def flush(self) -> None:
        self.flushed = True


@pytest.mark.asyncio
async def test_save_inbound_record_persists_model_and_outbox_event() -> None:
    session = FakeAsyncSession()
    repo = SqlAlchemyInboundRecordRepository(cast(AsyncSession, session))

    record = InboundRecord.create(
        tenant_id="tenant-123",
        connection_id="conn-456",
        app_id="salesforce",
        stream_name="contacts",
        business_trace_id="trace-789",
        business_correlation_id="corr-111",
        payload_bytes=b'{"id": "1"}',
        is_inlined=True,
        request_headers={"Content-Type": "application/json"},
        request_body={"id": "1"},
        response_status_code=200,
        response_headers={"X-Status": "ok"},
        response_body={"success": True},
        duration_ms=45,
    )

    await repo.save(record)

    assert len(session.added_records) == 2
    orm_model = next(r for r in session.added_records if isinstance(r, InboundRecordModel))
    outbox_record = next(r for r in session.added_records if isinstance(r, IpOutboxRecord))

    assert orm_model.id == record.id
    assert orm_model.tenant_id == "tenant-123"
    assert orm_model.request_body == {"id": "1"}
    assert orm_model.response_body == {"success": True}
    assert orm_model.duration_ms == 45

    assert outbox_record.tenant_id == "tenant-123"
    assert outbox_record.event_type == "ip.inbound_record.created"
    assert len(record.domain_events) == 0


@pytest.mark.asyncio
async def test_get_inbound_record_by_id_maps_to_domain() -> None:
    orm_model = InboundRecordModel(
        id="ip_inb_test123",
        tenant_id="tenant-123",
        connection_id="conn-456",
        app_id="salesforce",
        business_trace_id="trace-789",
        business_correlation_id="corr-111",
        stream_name="contacts",
        request_headers={"Content-Type": "application/json"},
        request_body={"id": "1"},
        request_s3_key=None,
        request_size_bytes=11,
        request_sha256="abc",
        response_status_code=200,
        response_headers={"X-Res": "ok"},
        response_body={"status": "received"},
        response_s3_key=None,
        duration_ms=30,
        received_at=datetime.now(UTC),
    )

    session = FakeAsyncSession(query_result=orm_model)
    repo = SqlAlchemyInboundRecordRepository(cast(AsyncSession, session))

    found = await repo.get_by_id("ip_inb_test123", "tenant-123")
    assert found is not None
    assert found.id == "ip_inb_test123"
    assert found.tenant_id == "tenant-123"
    assert found.request_body == {"id": "1"}
    assert found.response_body == {"status": "received"}


@pytest.mark.asyncio
async def test_get_inbound_record_by_trace_id_returns_list() -> None:
    orm_model = InboundRecordModel(
        id="ip_inb_test123",
        tenant_id="tenant-123",
        connection_id="conn-456",
        app_id="salesforce",
        business_trace_id="trace-789",
        business_correlation_id=None,
        stream_name="contacts",
        request_headers={},
        request_body={"id": "1"},
        request_s3_key=None,
        request_size_bytes=11,
        request_sha256="abc",
        response_status_code=200,
        response_headers=None,
        response_body=None,
        response_s3_key=None,
        duration_ms=None,
        received_at=datetime.now(UTC),
    )

    session = FakeAsyncSession(query_result=[orm_model])
    repo = SqlAlchemyInboundRecordRepository(cast(AsyncSession, session))

    results = await repo.get_by_trace_id("trace-789", "tenant-123")
    assert len(results) == 1
    assert results[0].business_trace_id == "trace-789"


@pytest.mark.asyncio
async def test_save_outbound_record_persists_model_and_outbox_event() -> None:
    session = FakeAsyncSession()
    repo = SqlAlchemyOutboundRecordRepository(cast(AsyncSession, session))

    record = OutboundRecord.create_pending(
        tenant_id="tenant-123",
        connection_id="conn-456",
        app_id="salesforce",
        stream_name="orders",
        target_url="https://api.salesforce.com/orders",
        http_method="POST",
        payload_bytes=b'{"order_id": 99}',
        is_inlined=True,
        business_trace_id="trace-999",
        business_correlation_id="corr-999",
        request_headers={"Authorization": "Bearer token"},
        request_body={"order_id": 99},
    )

    await repo.save(record)

    assert len(session.added_records) == 2
    orm_model = next(r for r in session.added_records if isinstance(r, OutboundRecordModel))
    outbox_record = next(r for r in session.added_records if isinstance(r, IpOutboxRecord))

    assert orm_model.id == record.id
    assert orm_model.tenant_id == "tenant-123"
    assert orm_model.status == OutboundDispatchStatus.PENDING.value
    assert orm_model.target_url == "https://api.salesforce.com/orders"
    assert orm_model.http_method == "POST"
    assert orm_model.request_body == {"order_id": 99}

    assert outbox_record.tenant_id == "tenant-123"
    assert outbox_record.event_type == "ip.outbound_record.created"
    assert len(record.domain_events) == 0


@pytest.mark.asyncio
async def test_get_outbound_record_by_id_maps_to_domain() -> None:
    now = datetime.now(UTC)
    orm_model = OutboundRecordModel(
        id="ip_out_test999",
        tenant_id="tenant-123",
        connection_id="conn-456",
        app_id="salesforce",
        business_trace_id="trace-999",
        business_correlation_id="corr-999",
        stream_name="orders",
        target_url="https://api.salesforce.com/orders",
        http_method="POST",
        request_headers={"Content-Type": "application/json"},
        request_body={"order_id": 99},
        request_s3_key=None,
        request_size_bytes=17,
        request_sha256="hash-999",
        response_status_code=201,
        response_headers={"Location": "/orders/99"},
        response_body={"success": True},
        response_s3_key=None,
        duration_ms=120,
        attempt_number=1,
        status="DELIVERED",
        error_message=None,
        sent_at=now,
    )

    session = FakeAsyncSession(query_result=orm_model)
    repo = SqlAlchemyOutboundRecordRepository(cast(AsyncSession, session))

    found = await repo.get_by_id("ip_out_test999", "tenant-123")
    assert found is not None
    assert found.id == "ip_out_test999"
    assert found.status == OutboundDispatchStatus.DELIVERED
    assert found.response_status_code == 201
    assert found.duration_ms == 120
    assert found.sent_at == now


@pytest.mark.asyncio
async def test_get_outbound_record_by_trace_id_returns_list() -> None:
    orm_model = OutboundRecordModel(
        id="ip_out_test999",
        tenant_id="tenant-123",
        connection_id="conn-456",
        app_id="salesforce",
        business_trace_id="trace-999",
        business_correlation_id=None,
        stream_name="orders",
        target_url="https://api.salesforce.com/orders",
        http_method="POST",
        request_headers={},
        request_body=None,
        request_s3_key=None,
        request_size_bytes=0,
        request_sha256="hash-0",
        response_status_code=None,
        response_headers=None,
        response_body=None,
        response_s3_key=None,
        duration_ms=None,
        attempt_number=1,
        status="PENDING",
        error_message=None,
        sent_at=datetime.now(UTC),
    )

    session = FakeAsyncSession(query_result=[orm_model])
    repo = SqlAlchemyOutboundRecordRepository(cast(AsyncSession, session))

    results = await repo.get_by_trace_id("trace-999", "tenant-123")
    assert len(results) == 1
    assert results[0].business_trace_id == "trace-999"
    assert results[0].status == OutboundDispatchStatus.PENDING
