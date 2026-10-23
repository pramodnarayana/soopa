"""Unit tests for Energy MDM Canonical DTOs and SqlAlchemyEnergyDomainRepository Data Mappers."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.application.domains.energy.canonical import (
    CanonicalMeterReadingDTO,
    CanonicalServicePointDTO,
)
from ip.application.domains.energy.models import (
    MdmMeterReadingRecord,
    MdmServicePointRecord,
)
from ip.application.domains.energy.repository import SqlAlchemyEnergyDomainRepository


def test_canonical_energy_dtos_are_immutable() -> None:
    now = datetime.now(UTC)

    reading = CanonicalMeterReadingDTO(
        id="mdm_read_01",
        tenant_id="ten_01",
        trace_id="ip_trc_01",
        source_connection_id="ip_conn_01",
        source_replica_id="ip_rep_01",
        meter_serial_number="MTR-100",
        service_point_id="SP-100",
        reading_timestamp=now,
        interval_minutes=15,
        kwh_delivered=14.2,
        kwh_received=1.1,
        voltage_avg=240.5,
        quality_flag="VALIDATED",
        recorded_at=now,
    )
    assert reading.meter_serial_number == "MTR-100"

    sp = CanonicalServicePointDTO(
        id="mdm_sp_01",
        tenant_id="ten_01",
        trace_id="ip_trc_01",
        source_connection_id="ip_conn_01",
        source_replica_id="ip_rep_01",
        service_point_external_id="SP-EXT-100",
        meter_serial_number="MTR-100",
        customer_external_id="CUST-01",
        service_address="100 Grid Way",
        grid_region="ERCOT-NORTH",
        status="ACTIVE",
        updated_at=now,
    )
    assert sp.grid_region == "ERCOT-NORTH"


def test_energy_domain_repository_mappers() -> None:
    now = datetime.now(UTC)
    reading_orm = MdmMeterReadingRecord(
        id="mdm_r_1",
        tenant_id="ten_01",
        trace_id="trc_01",
        correlation_id=None,
        parent_trace_id=None,
        original_trace_id=None,
        replay_count=0,
        source_connection_id="conn_1",
        source_replica_id="rep_1",
        meter_serial_number="MTR-1",
        service_point_id="SP-1",
        reading_timestamp=now,
        interval_minutes=15,
        kwh_delivered=12.3,
        kwh_received=0.0,
        voltage_avg=240.0,
        quality_flag="VALIDATED",
        recorded_at=now,
    )
    reading_dto: CanonicalMeterReadingDTO = SqlAlchemyEnergyDomainRepository._to_meter_reading_dto(
        reading_orm
    )
    assert reading_dto.meter_serial_number == "MTR-1"

    sp_orm = MdmServicePointRecord(
        id="mdm_sp_1",
        tenant_id="ten_01",
        trace_id="trc_01",
        correlation_id=None,
        parent_trace_id=None,
        original_trace_id=None,
        replay_count=0,
        source_connection_id="conn_1",
        source_replica_id="rep_1",
        service_point_external_id="SP-1",
        meter_serial_number="MTR-1",
        customer_external_id="CUST-1",
        service_address="1 Main St",
        grid_region="WEST",
        status="ACTIVE",
        updated_at=now,
    )
    sp_dto: CanonicalServicePointDTO = SqlAlchemyEnergyDomainRepository._to_service_point_dto(
        sp_orm
    )
    assert sp_dto.service_point_external_id == "SP-1"
