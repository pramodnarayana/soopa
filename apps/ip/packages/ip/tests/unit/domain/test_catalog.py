"""Pure zero-mock domain unit tests for ConnectionCatalog, StreamSchema, and StreamField."""

from __future__ import annotations

from ip.engine.domain.connection.catalog import ConnectionCatalog
from ip.engine.domain.connection.stream_schema import StreamField, StreamSchema
from ip.engine.domain.exceptions import InvalidConnectionConfigError, IpErrorCode
from ip.engine.domain.replication.enums import SyncMode


def test_catalog_create_deterministic_hash_is_order_independent() -> None:
    """Catalog hash must be identical regardless of stream or field ordering."""
    stream_a_v1 = StreamSchema(
        name="records_alpha",
        fields=[
            StreamField(name="serial_number", data_type="string", nullable=False),
            StreamField(name="quantity", data_type="number", nullable=True),
        ],
        primary_key=["serial_number"],
        cursor_field="updated_at",
        supported_sync_modes=[SyncMode.FULL_REFRESH, SyncMode.INCREMENTAL],
    )
    stream_b_v1 = StreamSchema(
        name="events_beta",
        fields=[
            StreamField(name="event_id", data_type="string", nullable=False),
            StreamField(name="metric_value", data_type="number", nullable=False),
        ],
        primary_key=["event_id"],
        cursor_field="timestamp",
        supported_sync_modes=[SyncMode.INCREMENTAL, SyncMode.FULL_REFRESH],
    )

    # Reversed field and stream order
    stream_a_v2 = StreamSchema(
        name="records_alpha",
        fields=[
            StreamField(name="quantity", data_type="number", nullable=True),
            StreamField(name="serial_number", data_type="string", nullable=False),
        ],
        primary_key=["serial_number"],
        cursor_field="updated_at",
        supported_sync_modes=[SyncMode.INCREMENTAL, SyncMode.FULL_REFRESH],
    )

    cat_1 = ConnectionCatalog.create(
        connection_id="ip_conn_123",
        catalog_version=1,
        streams=[stream_a_v1, stream_b_v1],
    )
    cat_2 = ConnectionCatalog.create(
        connection_id="ip_conn_123",
        catalog_version=2,
        streams=[stream_b_v1, stream_a_v2],
    )

    assert cat_1.id.startswith("ip_cat_")
    assert cat_1.catalog_hash == cat_2.catalog_hash
    assert len(cat_1.catalog_hash) == 64


def test_catalog_hash_changes_when_schema_mutates() -> None:
    stream_v1 = StreamSchema(
        name="records_alpha",
        fields=[StreamField(name="serial_number", data_type="string", nullable=False)],
        primary_key=["serial_number"],
    )
    stream_v2 = StreamSchema(
        name="records_alpha",
        fields=[
            StreamField(name="serial_number", data_type="string", nullable=False),
            StreamField(name="schema_revision", data_type="string", nullable=True),
        ],
        primary_key=["serial_number"],
    )

    cat_1 = ConnectionCatalog.create(
        connection_id="ip_conn_123",
        catalog_version=1,
        streams=[stream_v1],
    )
    cat_2 = ConnectionCatalog.create(
        connection_id="ip_conn_123",
        catalog_version=2,
        streams=[stream_v2],
    )

    assert cat_1.catalog_hash != cat_2.catalog_hash


def test_catalog_get_stream_lookup() -> None:
    records_stream = StreamSchema(
        name="records_alpha",
        fields=[StreamField(name="id", data_type="string", nullable=False)],
        primary_key=["id"],
    )
    cat = ConnectionCatalog.create(
        connection_id="ip_conn_123",
        catalog_version=1,
        streams=[records_stream],
    )

    found = cat.get_stream("records_alpha")
    assert found is not None
    assert found.name == "records_alpha"
    assert cat.get_stream("non_existent_stream") is None


def test_catalog_try_create_returns_result_error_on_blank_connection_id() -> None:
    result = ConnectionCatalog.try_create(
        connection_id="   ",
        catalog_version=1,
        streams=[],
    )

    assert result.is_err is True
    assert isinstance(result.error, InvalidConnectionConfigError)
    assert result.error.code == IpErrorCode.INVALID_CONFIG
    assert result.error.details["field"] == "connection_id"


def test_catalog_try_create_succeeds_for_valid_input() -> None:
    result = ConnectionCatalog.try_create(
        connection_id="ip_conn_valid",
        catalog_version=1,
        streams=[],
    )

    assert result.is_ok is True
    assert result.value is not None
    assert result.value.connection_id == "ip_conn_valid"
    assert result.value.is_active is True
