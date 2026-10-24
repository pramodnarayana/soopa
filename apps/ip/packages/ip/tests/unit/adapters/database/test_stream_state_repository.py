"""Pure zero-mock Data Mapper unit tests for SqlAlchemyStreamStateRepository."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.engine.adapters.outbound.database.control_plane.stream_state_repository import (
    SqlAlchemyStreamStateRepository,
)
from ip.engine.adapters.outbound.database.models.control_plane import (
    ConnectionStreamStateRecord,
)
from ip.engine.domain.models.stream_state import ConnectionStreamState


def test_to_domain_model_mapping() -> None:
    now = datetime.now(UTC)
    record = ConnectionStreamStateRecord(
        id="ip_cst_12345",
        tenant_id="tenant_abc",
        connection_id="conn_xyz",
        stream_name="invoices",
        cursor_field="updated_at",
        cursor_value="2026-10-20T12:00:00Z",
        records_synced_count=150,
        last_synced_at=now,
    )

    domain = SqlAlchemyStreamStateRepository._to_domain_model(record)
    assert domain.id == "ip_cst_12345"
    assert domain.tenant_id == "tenant_abc"
    assert domain.connection_id == "conn_xyz"
    assert domain.stream_name == "invoices"
    assert domain.cursor_field == "updated_at"
    assert domain.cursor_value == "2026-10-20T12:00:00Z"
    assert domain.records_synced_count == 150
    assert domain.last_synced_at == now


def test_update_record_from_domain() -> None:
    now = datetime.now(UTC)
    record = ConnectionStreamStateRecord(
        id="ip_cst_12345",
        tenant_id="tenant_abc",
        connection_id="conn_xyz",
        stream_name="invoices",
        cursor_field="id",
        cursor_value="10",
        records_synced_count=10,
        last_synced_at=now,
    )
    domain = ConnectionStreamState(
        id="ip_cst_12345",
        tenant_id="tenant_abc",
        connection_id="conn_xyz",
        stream_name="invoices",
        cursor_field="id",
        cursor_value="25",
        records_synced_count=25,
        last_synced_at=now,
    )

    SqlAlchemyStreamStateRepository._update_record_from_domain(record, domain)
    assert record.cursor_value == "25"
    assert record.records_synced_count == 25
