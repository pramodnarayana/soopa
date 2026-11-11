"""Pure zero-mock unit tests for generic IP Engine SQLAlchemy repository mappers."""

from __future__ import annotations

from datetime import UTC, datetime

from identity.domain.constants import IdentityIdPrefix
from ip.engine.adapters.outbound.database.control_plane.catalog_repository import (
    SqlAlchemyCatalogRepository,
)
from ip.engine.adapters.outbound.database.control_plane.connection_repository import (
    SqlAlchemyConnectionRepository,
)
from ip.engine.adapters.outbound.database.control_plane.stream_state_repository import (
    SqlAlchemyStreamStateRepository,
)
from ip.engine.adapters.outbound.database.data_plane.entity_map_repository import (
    SqlAlchemyGlobalEntityMapRepository,
)
from ip.engine.adapters.outbound.database.data_plane.replica_record_repository import (
    SqlAlchemyReplicaRecordRepository,
)
from ip.engine.adapters.outbound.database.data_plane.replica_rejection_repository import (
    SqlAlchemyReplicaRejectionRepository,
)
from ip.engine.domain.connection.catalog import ConnectionCatalog
from ip.engine.domain.connection.connection import Connection
from ip.engine.domain.connection.enums import AuthType, ConnectionStatus
from ip.engine.domain.connection.stream_schema import StreamField, StreamSchema
from ip.engine.domain.enums import IpIdPrefix
from ip.engine.domain.normalization.normalized_record import GlobalEntityMap
from ip.engine.domain.replication.enums import CursorKind, RejectionReason, SyncMode
from ip.engine.domain.replication.replica_record import ReplicaRecord, ReplicaRejection
from ip.engine.domain.replication.stream_state import ConnectionStreamState
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id


def test_replica_rejection_repository_bidirectional_mapper() -> None:
    now = datetime.now(UTC)
    rejection = ReplicaRejection(
        id=generate_id(IpIdPrefix.REPLICA_REJECTION.value),
        tenant_id=generate_id(IdentityIdPrefix.TENANT.value),
        connection_id=generate_id(IpIdPrefix.CONNECTION.value),
        stream="records_alpha",
        inbound_record_id=generate_id(IpIdPrefix.INBOUND_RECORD.value),
        record_index=0,
        reason=RejectionReason.MISSING_PRIMARY_KEY,
        detail="Missing id",
        trace_id=generate_id(IpIdPrefix.TRACE.value),
        created_at=now,
    )
    rej_orm = SqlAlchemyReplicaRejectionRepository._to_orm_model(rejection)
    rej_round_trip = SqlAlchemyReplicaRejectionRepository._to_domain_model(rej_orm)
    assert rej_round_trip == rejection


def test_global_entity_map_repository_bidirectional_mapper() -> None:
    now = datetime.now(UTC)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    src_conn_id = generate_id(IpIdPrefix.CONNECTION.value)
    dst_conn_id = generate_id(IpIdPrefix.CONNECTION.value)
    trace_id = generate_id(IpIdPrefix.TRACE.value)
    correlation_id = generate_id(SystemIdPrefix.GENERIC.value)
    canonical_id = generate_id(IpIdPrefix.CANONICAL.value)

    gem = GlobalEntityMap(
        id=generate_id(IpIdPrefix.GEM.value),
        tenant_id=tenant_id,
        trace_id=trace_id,
        correlation_id=correlation_id,
        entity_domain="SYNTHETIC_ENTITY",
        canonical_id=canonical_id,
        source_connection_id=src_conn_id,
        source_entity_id="SRC_01",
        dest_connection_id=dst_conn_id,
        dest_entity_id="DST_01",
        created_at=now,
    )
    gem_orm = SqlAlchemyGlobalEntityMapRepository._to_orm_model(gem)
    gem_round_trip = SqlAlchemyGlobalEntityMapRepository._to_domain_model(gem_orm)
    assert gem_round_trip.id == gem.id
    assert gem_round_trip.tenant_id == tenant_id
    assert gem_round_trip.trace_id == trace_id
    assert gem_round_trip.correlation_id == correlation_id
    assert gem_round_trip.parent_trace_id is None
    assert gem_round_trip.original_trace_id is None
    assert gem_round_trip.replay_count == 0
    assert gem_round_trip.entity_domain == "SYNTHETIC_ENTITY"
    assert gem_round_trip.canonical_id == canonical_id
    assert gem_round_trip.source_connection_id == src_conn_id
    assert gem_round_trip.source_entity_id == "SRC_01"
    assert gem_round_trip.dest_connection_id == dst_conn_id
    assert gem_round_trip.dest_entity_id == "DST_01"
    assert gem_round_trip.created_at == now

    updated_canonical_id = generate_id(IpIdPrefix.CANONICAL.value)
    updated_trace_id = generate_id(IpIdPrefix.TRACE.value)
    updated_gem = GlobalEntityMap(
        id=gem.id,
        tenant_id=tenant_id,
        trace_id=updated_trace_id,
        correlation_id=correlation_id,
        parent_trace_id=trace_id,
        original_trace_id=trace_id,
        replay_count=1,
        entity_domain="SYNTHETIC_ENTITY",
        canonical_id=updated_canonical_id,
        source_connection_id=src_conn_id,
        source_entity_id="SRC_01",
        dest_connection_id=dst_conn_id,
        dest_entity_id="DST_02",
        created_at=now,
    )
    SqlAlchemyGlobalEntityMapRepository._update_record_from_domain(gem_orm, updated_gem)
    updated_gem_round_trip = SqlAlchemyGlobalEntityMapRepository._to_domain_model(gem_orm)
    assert updated_gem_round_trip.canonical_id == updated_canonical_id
    assert updated_gem_round_trip.trace_id == updated_trace_id
    assert updated_gem_round_trip.parent_trace_id == trace_id
    assert updated_gem_round_trip.original_trace_id == trace_id
    assert updated_gem_round_trip.replay_count == 1
    assert updated_gem_round_trip.dest_entity_id == "DST_02"


def test_replica_record_repository_bidirectional_mapper() -> None:
    replica = ReplicaRecord.create(
        tenant_id=generate_id(IdentityIdPrefix.TENANT.value),
        connection_id=generate_id(IpIdPrefix.CONNECTION.value),
        stream="records_alpha",
        record_key="REC-1",
        primary_key_values=("REC-1",),
        cursor_value="2026-11-02T00:00:00Z",
        cursor_kind=CursorKind.DATETIME.value,
        data={"id": "REC-1", "total": 100},
        generation_id=1,
        source_inbound_record_id=generate_id(IpIdPrefix.INBOUND_RECORD.value),
        trace_id=generate_id(IpIdPrefix.TRACE.value),
        correlation_id=generate_id(SystemIdPrefix.GENERIC.value),
    )
    replica_orm = SqlAlchemyReplicaRecordRepository._to_orm_model(replica)
    assert SqlAlchemyReplicaRecordRepository._to_domain_model(replica_orm).record_key == "REC-1"


def test_control_plane_repository_bidirectional_mappers() -> None:
    now = datetime.now(UTC)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    connection_id = generate_id(IpIdPrefix.CONNECTION.value)

    catalog = ConnectionCatalog(
        id=generate_id(IpIdPrefix.CATALOG.value),
        tenant_id=tenant_id,
        connection_id=connection_id,
        catalog_version=1,
        catalog_hash="sha256_catalog_digest",
        streams=[
            StreamSchema(
                name="records_alpha",
                fields=[StreamField(name="id", data_type="string", nullable=False)],
                primary_key=["id"],
                cursor_field="updated_at",
                supported_sync_modes=[SyncMode.INCREMENTAL],
            )
        ],
        is_active=True,
        discovered_at=now.isoformat(),
    )
    cat_orm = SqlAlchemyCatalogRepository._to_orm_model(catalog)
    restored_cat = SqlAlchemyCatalogRepository._to_domain_model(cat_orm)
    assert restored_cat.tenant_id == tenant_id
    assert restored_cat.streams[0].name == "records_alpha"

    connection = Connection(
        id=connection_id,
        tenant_id=tenant_id,
        app_id="acme_http",
        name="Acme Prod",
        auth_type=AuthType.OAUTH2,
        public_config={"base_url": "https://api.acme.example.com"},
        encrypted_credentials=b"enc_blob",
        key_encryption_version=1,
        connection_fingerprint="sha256_conn_fingerprint",
        status=ConnectionStatus.ACTIVE,
        token_expires_at=None,
        last_refreshed_at=None,
        last_error_code=None,
        last_error_message=None,
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
        deactivated_at=None,
    )
    conn_orm = SqlAlchemyConnectionRepository._to_orm_model(connection)
    assert SqlAlchemyConnectionRepository._to_domain_model(conn_orm).name == "Acme Prod"

    state = ConnectionStreamState(
        id=generate_id(IpIdPrefix.STREAM_STATE.value),
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name="records_alpha",
        cursor_field="updated_at",
        cursor_value="2026-11-02T00:00:00Z",
        records_synced_count=25,
        last_synced_at=now,
    )
    state_orm = SqlAlchemyStreamStateRepository._to_orm_model(state)
    assert SqlAlchemyStreamStateRepository._to_domain_model(state_orm).records_synced_count == 25
