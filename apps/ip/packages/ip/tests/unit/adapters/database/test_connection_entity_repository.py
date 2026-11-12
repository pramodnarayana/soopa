"""Pure zero-mock Data Mapper unit tests for SqlAlchemyConnectionEntityRepository."""

from __future__ import annotations

from datetime import UTC, datetime

from identity.domain.constants import IdentityIdPrefix
from ip.engine.adapters.outbound.database.control_plane.connection_entity_repository import (
    SqlAlchemyConnectionEntityRepository,
)
from ip.engine.adapters.outbound.database.models.control_plane import (
    ConnectionEntityRecord,
)
from ip.engine.domain.connection.stream_schema import StreamField
from ip.engine.domain.constants import IpIdPrefix
from ip.engine.domain.replication.connection_entity import ConnectionEntity
from ip.engine.domain.replication.enums import EntitySyncFrom, EntitySyncSchedule, SyncMode
from seedwork.utils import generate_id


def test_to_domain_model_mapping() -> None:
    now = datetime.now(UTC)
    entity_id = generate_id(IpIdPrefix.CONNECTION_ENTITY.value)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    connection_id = generate_id(IpIdPrefix.CONNECTION.value)
    record = ConnectionEntityRecord(
        id=entity_id,
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name="invoices",
        sync_mode="INCREMENTAL",
        schedule="15m",
        sync_from="all",
        sync_from_at=None,
        is_enabled=True,
        primary_key=["id"],
        fields_schema=[
            {"name": "id", "data_type": "string", "nullable": False, "description": "Primary ID"}
        ],
        cursor_field="updated_at",
        cursor_value="2026-10-20T12:00:00Z",
        records_synced_count=150,
        last_synced_at=now,
        created_at=now,
        updated_at=now,
    )

    domain = SqlAlchemyConnectionEntityRepository._to_domain_model(record)
    assert domain.id == entity_id
    assert domain.tenant_id == tenant_id
    assert domain.connection_id == connection_id
    assert domain.stream_name == "invoices"
    assert domain.sync_mode == SyncMode.INCREMENTAL
    assert domain.schedule == EntitySyncSchedule.EVERY_15M
    assert domain.sync_from == EntitySyncFrom.ALL
    assert domain.primary_key == ("id",)
    assert len(domain.fields) == 1
    assert domain.fields[0].name == "id"
    assert domain.fields[0].nullable is False
    assert domain.cursor_field == "updated_at"
    assert domain.cursor_value == "2026-10-20T12:00:00Z"
    assert domain.records_synced_count == 150
    assert domain.last_synced_at == now


def test_update_record_from_domain() -> None:
    now = datetime.now(UTC)
    entity_id = generate_id(IpIdPrefix.CONNECTION_ENTITY.value)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    connection_id = generate_id(IpIdPrefix.CONNECTION.value)
    record = ConnectionEntityRecord(
        id=entity_id,
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name="invoices",
        sync_mode="INCREMENTAL",
        schedule="manual",
        sync_from="all",
        sync_from_at=None,
        is_enabled=True,
        primary_key=[],
        fields_schema=[],
        cursor_field="id",
        cursor_value="10",
        records_synced_count=10,
        last_synced_at=now,
        created_at=now,
        updated_at=now,
    )
    domain = ConnectionEntity(
        id=entity_id,
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name="invoices",
        sync_mode=SyncMode.FULL_REFRESH,
        schedule=EntitySyncSchedule.DAILY,
        sync_from=EntitySyncFrom.LAST_7D,
        sync_from_at=None,
        is_enabled=False,
        primary_key=("invoice_id",),
        fields=(StreamField(name="invoice_id", data_type="string", nullable=False),),
        cursor_field="id",
        cursor_value="25",
        records_synced_count=25,
        last_synced_at=now,
        created_at=now,
        updated_at=now,
    )

    SqlAlchemyConnectionEntityRepository._update_record_from_domain(record, domain)
    assert record.sync_mode == "FULL_REFRESH"
    assert record.schedule == "24h"
    assert record.sync_from == "7d"
    assert record.is_enabled is False
    assert record.primary_key == ["invoice_id"]
    assert len(record.fields_schema) == 1
    assert record.cursor_value == "25"
    assert record.records_synced_count == 25
