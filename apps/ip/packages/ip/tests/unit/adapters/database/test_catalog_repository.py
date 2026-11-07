"""Pure zero-mock Data Mapper unit tests for SqlAlchemyCatalogRepository."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.engine.adapters.outbound.database.control_plane.catalog_repository import (
    SqlAlchemyCatalogRepository,
)
from ip.engine.adapters.outbound.database.models.control_plane import ConnectionCatalogRecord
from ip.engine.domain.connection.catalog import ConnectionCatalog
from ip.engine.domain.connection.stream_schema import StreamField, StreamSchema
from ip.engine.domain.replication.enums import SyncMode


def test_catalog_schema_roundtrip_mapping() -> None:
    now = datetime.now(UTC)
    catalog = ConnectionCatalog.create(
        connection_id="ip_conn_12345",
        catalog_version=3,
        streams=[
            StreamSchema(
                name="records_alpha",
                fields=[
                    StreamField(
                        name="serial_number",
                        data_type="string",
                        nullable=False,
                        description="Unique record serial",
                    ),
                    StreamField(
                        name="amount",
                        data_type="number",
                        nullable=True,
                        description=None,
                    ),
                ],
                primary_key=["serial_number"],
                cursor_field="updated_at",
                supported_sync_modes=[SyncMode.FULL_REFRESH, SyncMode.INCREMENTAL],
            )
        ],
    )

    serialized = SqlAlchemyCatalogRepository._serialize_schema_definition(catalog)
    record = ConnectionCatalogRecord(
        id=catalog.id,
        connection_id=catalog.connection_id,
        catalog_version=catalog.catalog_version,
        catalog_hash=catalog.catalog_hash,
        schema_definition=serialized,
        is_active=True,
        discovered_at=now,
    )

    restored = SqlAlchemyCatalogRepository._to_domain_model(record)

    assert restored.id == catalog.id
    assert restored.connection_id == "ip_conn_12345"
    assert restored.catalog_version == 3
    assert restored.catalog_hash == catalog.catalog_hash
    assert len(restored.streams) == 1
    stream = restored.streams[0]
    assert stream.name == "records_alpha"
    assert list(stream.primary_key) == ["serial_number"]
    assert stream.cursor_field == "updated_at"
    assert len(stream.fields) == 2
    assert stream.fields[0].name == "serial_number"
    assert stream.fields[0].nullable is False
    assert stream.fields[0].description == "Unique record serial"
