"""Pure zero-mock Phase 4 unit tests for IP SQLAlchemy _to_domain_model and _to_orm_model mappers."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

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
from ip.solutions.domains.energy.canonical import (
    CanonicalMeterReadingDTO,
    CanonicalServicePointDTO,
)
from ip.solutions.domains.energy.repository import SqlAlchemyEnergyDomainRepository
from ip.solutions.domains.tms.canonical import CanonicalCarrierDTO, CanonicalLoadDTO
from ip.solutions.domains.tms.repository import SqlAlchemyTmsDomainRepository
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id


def test_ip_data_plane_and_control_plane_to_orm_and_domain_mappers() -> None:
    now = datetime.now(UTC)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    connection_id = generate_id(IpIdPrefix.CONNECTION.value)
    src_conn_id = generate_id(IpIdPrefix.CONNECTION.value)
    dst_conn_id = generate_id(IpIdPrefix.CONNECTION.value)
    inbound_id = generate_id(IpIdPrefix.INBOUND_RECORD.value)
    trace_id = generate_id(IpIdPrefix.TRACE.value)
    correlation_id = generate_id(SystemIdPrefix.GENERIC.value)

    rejection = ReplicaRejection(
        id=generate_id(IpIdPrefix.REPLICA_REJECTION.value),
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream="orders",
        inbound_record_id=inbound_id,
        record_index=0,
        reason=RejectionReason.MISSING_PRIMARY_KEY,
        detail="Missing id",
        trace_id=trace_id,
        created_at=now,
    )
    rej_orm = SqlAlchemyReplicaRejectionRepository._to_orm_model(rejection)
    rej_round_trip = SqlAlchemyReplicaRejectionRepository._to_domain_model(rej_orm)
    assert rej_round_trip == rejection

    canonical_id = generate_id(IpIdPrefix.TMS_LOAD.value)
    gem = GlobalEntityMap(
        id=generate_id(IpIdPrefix.GEM.value),
        tenant_id=tenant_id,
        trace_id=trace_id,
        correlation_id=correlation_id,
        entity_domain="TMS_LOAD",
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
    assert gem_round_trip.entity_domain == "TMS_LOAD"
    assert gem_round_trip.canonical_id == canonical_id
    assert gem_round_trip.source_connection_id == src_conn_id
    assert gem_round_trip.source_entity_id == "SRC_01"
    assert gem_round_trip.dest_connection_id == dst_conn_id
    assert gem_round_trip.dest_entity_id == "DST_01"
    assert gem_round_trip.created_at == now

    updated_canonical_id = generate_id(IpIdPrefix.TMS_LOAD.value)
    updated_trace_id = generate_id(IpIdPrefix.TRACE.value)
    updated_gem = GlobalEntityMap(
        id=gem.id,
        tenant_id=tenant_id,
        trace_id=updated_trace_id,
        correlation_id=correlation_id,
        parent_trace_id=trace_id,
        original_trace_id=trace_id,
        replay_count=1,
        entity_domain="TMS_LOAD",
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

    replica = ReplicaRecord.create(
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream="orders",
        record_key="ORD-1",
        primary_key_values=("ORD-1",),
        cursor_value="2026-11-02T00:00:00Z",
        cursor_kind=CursorKind.DATETIME.value,
        data={"id": "ORD-1", "total": 100},
        generation_id=1,
        source_inbound_record_id=inbound_id,
        trace_id=trace_id,
        correlation_id=correlation_id,
    )
    replica_orm = SqlAlchemyReplicaRecordRepository._to_orm_model(replica)
    assert SqlAlchemyReplicaRecordRepository._to_domain_model(replica_orm).record_key == "ORD-1"

    catalog = ConnectionCatalog(
        id=generate_id(IpIdPrefix.CATALOG.value),
        connection_id=connection_id,
        catalog_version=1,
        catalog_hash="sha256_catalog_digest",
        streams=[
            StreamSchema(
                name="orders",
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
    assert SqlAlchemyCatalogRepository._to_domain_model(cat_orm).streams[0].name == "orders"

    connection = Connection(
        id=connection_id,
        tenant_id=tenant_id,
        app_id="salesforce",
        name="SF Prod",
        auth_type=AuthType.OAUTH2,
        public_config={"instance_url": "https://acme.my.salesforce.com"},
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
    assert SqlAlchemyConnectionRepository._to_domain_model(conn_orm).name == "SF Prod"

    state = ConnectionStreamState(
        id=generate_id(IpIdPrefix.STREAM_STATE.value),
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name="orders",
        cursor_field="updated_at",
        cursor_value="2026-11-02T00:00:00Z",
        records_synced_count=25,
        last_synced_at=now,
    )
    state_orm = SqlAlchemyStreamStateRepository._to_orm_model(state)
    assert SqlAlchemyStreamStateRepository._to_domain_model(state_orm).records_synced_count == 25


def test_ip_solution_domain_repositories_have_explicit_bidirectional_mappers() -> None:
    now = datetime.now(UTC)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    trace_id = generate_id(IpIdPrefix.TRACE.value)
    connection_id = generate_id(IpIdPrefix.CONNECTION.value)
    replica_id = generate_id(IpIdPrefix.REPLICA.value)
    tx_id = generate_id(IpIdPrefix.TRANSFORMATION.value)
    sp_id = generate_id(IpIdPrefix.MDM_SERVICE_POINT.value)
    mr_id = generate_id(IpIdPrefix.MDM_READING.value)
    load_id = generate_id(IpIdPrefix.TMS_LOAD.value)
    carrier_id = generate_id(IpIdPrefix.TMS_CARRIER.value)

    reading_dto = CanonicalMeterReadingDTO(
        id=mr_id,
        tenant_id=tenant_id,
        trace_id=trace_id,
        correlation_id=None,
        parent_trace_id=None,
        original_trace_id=None,
        replay_count=0,
        source_connection_id=connection_id,
        source_replica_id=replica_id,
        transformation_id=tx_id,
        transformation_version=1,
        meter_serial_number="MTR-100",
        service_point_id=sp_id,
        reading_timestamp=now,
        interval_minutes=15,
        kwh_delivered=12.5,
        kwh_received=0.0,
        voltage_avg=240.1,
        quality_flag="VALID",
        recorded_at=now,
    )
    mr_orm = SqlAlchemyEnergyDomainRepository._to_meter_reading_orm(reading_dto)
    assert SqlAlchemyEnergyDomainRepository._to_meter_reading_dto(mr_orm) == reading_dto

    sp_dto = CanonicalServicePointDTO(
        id=sp_id,
        tenant_id=tenant_id,
        trace_id=trace_id,
        correlation_id=None,
        parent_trace_id=None,
        original_trace_id=None,
        replay_count=0,
        source_connection_id=connection_id,
        source_replica_id=replica_id,
        transformation_id=tx_id,
        transformation_version=1,
        service_point_external_id="SP-EXT-1",
        meter_serial_number="MTR-100",
        customer_external_id="CUST-1",
        service_address="100 Main St",
        grid_region="WECC",
        status="ACTIVE",
        updated_at=now,
    )
    sp_orm = SqlAlchemyEnergyDomainRepository._to_service_point_orm(sp_dto, resolved_id=sp_id)
    assert SqlAlchemyEnergyDomainRepository._to_service_point_dto(sp_orm) == sp_dto

    load_dto = CanonicalLoadDTO(
        id=load_id,
        tenant_id=tenant_id,
        trace_id=trace_id,
        correlation_id=None,
        parent_trace_id=None,
        original_trace_id=None,
        replay_count=0,
        source_connection_id=connection_id,
        source_replica_id=replica_id,
        load_reference_number="LD-900",
        carrier_scac="ABCD",
        origin_city="Dallas",
        origin_state="TX",
        destination_city="Chicago",
        destination_state="IL",
        status="IN_TRANSIT",
        total_weight_lbs=40000,
        freight_charge_usd=Decimal("2450.00"),
        pickup_scheduled_at=now,
        delivery_scheduled_at=now,
        updated_at=now,
    )
    load_orm = SqlAlchemyTmsDomainRepository._to_load_orm(load_dto, resolved_id=load_id)
    assert SqlAlchemyTmsDomainRepository._to_load_dto(load_orm) == load_dto

    carrier_dto = CanonicalCarrierDTO(
        id=carrier_id,
        tenant_id=tenant_id,
        trace_id=trace_id,
        correlation_id=None,
        parent_trace_id=None,
        original_trace_id=None,
        replay_count=0,
        source_connection_id=connection_id,
        source_replica_id=replica_id,
        scac_code="ABCD",
        carrier_name="ABCD Freight",
        dot_number="123456",
        mc_number="MC654321",
        safety_rating="SATISFACTORY",
        status="ACTIVE",
        updated_at=now,
    )
    carrier_orm = SqlAlchemyTmsDomainRepository._to_carrier_orm(carrier_dto, resolved_id=carrier_id)
    assert SqlAlchemyTmsDomainRepository._to_carrier_dto(carrier_orm) == carrier_dto
