"""Pure zero-mock Phase 4 unit tests for IP SQLAlchemy _to_domain_model and _to_orm_model mappers."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from database.provider import DatabaseProvider, get_async_engine
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
from ip.engine.adapters.outbound.database.models.base import IpTenantBase
from ip.engine.domain.connection.catalog import ConnectionCatalog
from ip.engine.domain.connection.connection import Connection
from ip.engine.domain.connection.enums import AuthType, ConnectionStatus
from ip.engine.domain.connection.stream_schema import StreamField, StreamSchema
from ip.engine.domain.enums import IpIdPrefix
from ip.engine.domain.normalization.normalized_record import GlobalEntityMap
from ip.engine.domain.replication.enums import CursorKind, RejectionReason, SyncMode
from ip.engine.domain.replication.replica_record import ReplicaRecord, ReplicaRejection
from ip.engine.domain.replication.stream_state import ConnectionStreamState
from ip.solutions.domains.energy import models as _energy_models
from ip.solutions.domains.energy.canonical import (
    CanonicalMeterReadingDTO,
    CanonicalServicePointDTO,
)
from ip.solutions.domains.energy.ports import ENERGY_DOMAIN_REPOSITORY_KEY
from ip.solutions.domains.energy.repository import SqlAlchemyEnergyDomainRepository
from ip.solutions.domains.tms import models as _tms_models
from ip.solutions.domains.tms.canonical import CanonicalCarrierDTO, CanonicalLoadDTO
from ip.solutions.domains.tms.ports import TMS_DOMAIN_REPOSITORY_KEY
from ip.solutions.domains.tms.repository import SqlAlchemyTmsDomainRepository
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

_REGISTERED_VERTICAL_MODELS = (_energy_models, _tms_models)


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type: JSONB, _compiler: object, **_kw: object) -> str:
    return "JSON"


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


@pytest.mark.asyncio
async def test_ip_solution_domain_repositories_persist_and_read_back_all_fields() -> None:
    provider = DatabaseProvider(get_async_engine("sqlite+aiosqlite:///:memory:"))
    try:
        async with provider.engine.begin() as conn:
            await conn.run_sync(IpTenantBase.metadata.create_all)

        async with provider.session_factory() as session:
            energy_repo = SqlAlchemyEnergyDomainRepository(session)
            tms_repo = SqlAlchemyTmsDomainRepository(session)

            assert ENERGY_DOMAIN_REPOSITORY_KEY.narrow(energy_repo) is energy_repo
            assert TMS_DOMAIN_REPOSITORY_KEY.narrow(tms_repo) is tms_repo

            tenant_id = "ten_domain_rt"
            reading_ts = datetime(2026, 11, 3, 6, 15, 0, tzinfo=UTC)
            recorded_ts = datetime(2026, 11, 3, 6, 16, 0, tzinfo=UTC)

            sp_dto = CanonicalServicePointDTO(
                id="ip_mdms_rt_1",
                tenant_id=tenant_id,
                trace_id="ip_trc_rt_1",
                correlation_id="CORR-SP-1",
                parent_trace_id="ip_trc_parent_1",
                original_trace_id="ip_trc_orig_1",
                replay_count=2,
                source_connection_id="ip_conn_itron",
                source_replica_id="ip_rep_sp_1",
                transformation_id="energy.ami_service_point",
                transformation_version=1,
                service_point_external_id="SP-EXT-RT-1",
                meter_serial_number="MTR-RT-1",
                customer_external_id="CUST-RT-1",
                service_address="500 Energy Plaza",
                grid_region="ERCOT",
                status="ACTIVE",
                updated_at=recorded_ts,
            )
            await energy_repo.save_service_point(sp_dto)

            reading_dto = CanonicalMeterReadingDTO(
                id="ip_mdmr_rt_1",
                tenant_id=tenant_id,
                trace_id="ip_trc_rt_1",
                correlation_id="CORR-MR-1",
                parent_trace_id="ip_trc_parent_1",
                original_trace_id="ip_trc_orig_1",
                replay_count=1,
                source_connection_id="ip_conn_itron",
                source_replica_id="ip_rep_mr_1",
                transformation_id="energy.ami_meter_reading",
                transformation_version=2,
                meter_serial_number="MTR-RT-1",
                service_point_id="SP-EXT-RT-1",
                reading_timestamp=reading_ts,
                interval_minutes=15,
                kwh_delivered=18.4,
                kwh_received=0.5,
                voltage_avg=241.0,
                quality_flag="VALIDATED",
                recorded_at=recorded_ts,
            )
            await energy_repo.save_meter_reading(reading_dto)

            persisted_sp = await energy_repo.get_service_point_by_external_id(
                tenant_id, "SP-EXT-RT-1"
            )
            assert persisted_sp is not None
            assert persisted_sp.id == "ip_mdms_rt_1"
            assert persisted_sp.meter_serial_number == "MTR-RT-1"
            assert persisted_sp.customer_external_id == "CUST-RT-1"
            assert persisted_sp.service_address == "500 Energy Plaza"
            assert persisted_sp.grid_region == "ERCOT"
            assert persisted_sp.status == "ACTIVE"
            assert persisted_sp.replay_count == 2
            assert persisted_sp.updated_at.replace(tzinfo=UTC) == recorded_ts

            readings = await energy_repo.list_readings_by_meter(tenant_id, "MTR-RT-1")
            assert len(readings) == 1
            persisted_mr = readings[0]
            assert persisted_mr.id == "ip_mdmr_rt_1"
            assert persisted_mr.service_point_id == "SP-EXT-RT-1"
            assert persisted_mr.reading_timestamp.replace(tzinfo=UTC) == reading_ts
            assert persisted_mr.interval_minutes == 15
            assert persisted_mr.kwh_delivered == 18.4
            assert persisted_mr.kwh_received == 0.5
            assert persisted_mr.voltage_avg == 241.0
            assert persisted_mr.quality_flag == "VALIDATED"
            assert persisted_mr.transformation_version == 2
            assert persisted_mr.replay_count == 1

            carrier_dto = CanonicalCarrierDTO(
                id="ip_tmsc_rt_1",
                tenant_id=tenant_id,
                trace_id="ip_trc_rt_2",
                correlation_id="CORR-CAR-1",
                parent_trace_id="ip_trc_parent_2",
                original_trace_id="ip_trc_orig_2",
                replay_count=1,
                source_connection_id="ip_conn_mg",
                source_replica_id="ip_rep_car_1",
                scac_code="SWFT",
                carrier_name="Swift Transportation",
                dot_number="DOT-999",
                mc_number="MC-999",
                safety_rating="SATISFACTORY",
                status="ACTIVE",
                updated_at=recorded_ts,
            )
            await tms_repo.save_carrier(carrier_dto)

            load_dto = CanonicalLoadDTO(
                id="ip_tmsl_rt_1",
                tenant_id=tenant_id,
                trace_id="ip_trc_rt_2",
                correlation_id="CORR-LD-1",
                parent_trace_id="ip_trc_parent_2",
                original_trace_id="ip_trc_orig_2",
                replay_count=3,
                source_connection_id="ip_conn_mg",
                source_replica_id="ip_rep_ld_1",
                load_reference_number="LOAD-700",
                carrier_scac="SWFT",
                origin_city="Houston",
                origin_state="TX",
                destination_city="Chicago",
                destination_state="IL",
                status="IN_TRANSIT",
                total_weight_lbs=38500.0,
                freight_charge_usd=Decimal("3100.25"),
                pickup_scheduled_at=reading_ts,
                delivery_scheduled_at=recorded_ts,
                updated_at=recorded_ts,
            )
            await tms_repo.save_load(load_dto)

            persisted_carrier = await tms_repo.get_carrier_by_scac(tenant_id, "SWFT")
            assert persisted_carrier is not None
            assert persisted_carrier.id == "ip_tmsc_rt_1"
            assert persisted_carrier.scac_code == "SWFT"
            assert persisted_carrier.carrier_name == "Swift Transportation"
            assert persisted_carrier.dot_number == "DOT-999"
            assert persisted_carrier.mc_number == "MC-999"
            assert persisted_carrier.safety_rating == "SATISFACTORY"
            assert persisted_carrier.status == "ACTIVE"
            assert persisted_carrier.replay_count == 1
            assert persisted_carrier.updated_at.replace(tzinfo=UTC) == recorded_ts

            loads = await tms_repo.list_loads_by_status(tenant_id, "IN_TRANSIT")
            assert len(loads) == 1
            persisted_load = loads[0]
            assert persisted_load.id == "ip_tmsl_rt_1"
            assert persisted_load.load_reference_number == "LOAD-700"
            assert persisted_load.carrier_scac == "SWFT"
            assert persisted_load.origin_city == "Houston"
            assert persisted_load.origin_state == "TX"
            assert persisted_load.destination_city == "Chicago"
            assert persisted_load.destination_state == "IL"
            assert persisted_load.total_weight_lbs == 38500.0
            assert isinstance(persisted_load.freight_charge_usd, Decimal)
            assert persisted_load.freight_charge_usd == Decimal("3100.25")
            assert persisted_load.pickup_scheduled_at is not None
            assert persisted_load.pickup_scheduled_at.replace(tzinfo=UTC) == reading_ts
            assert persisted_load.delivery_scheduled_at is not None
            assert persisted_load.delivery_scheduled_at.replace(tzinfo=UTC) == recorded_ts
            assert persisted_load.replay_count == 3
    finally:
        await provider.close()
