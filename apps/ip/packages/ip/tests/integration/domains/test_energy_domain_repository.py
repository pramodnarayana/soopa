"""Narrow Integration Tests for SqlAlchemyEnergyDomainRepository against real PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from database.types import TenantSession
from ip.solutions.domains.energy.canonical import (
    CanonicalMeterReadingDTO,
    CanonicalServicePointDTO,
)
from ip.solutions.domains.energy.repository import SqlAlchemyEnergyDomainRepository

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_canonical_energy_domain_repository(
    tenant_session: TenantSession,
) -> None:
    energy_repo = SqlAlchemyEnergyDomainRepository(tenant_session)
    tenant_id = "ten_dp_energy"
    now = datetime.now(UTC)

    await energy_repo.save_service_point(
        CanonicalServicePointDTO(
            id="ip_mdms_001",
            tenant_id=tenant_id,
            trace_id="ip_trc_dom_1",
            source_connection_id="ip_conn_itron",
            source_replica_id="ip_rep_001",
            service_point_external_id="SP-EXT-001",
            meter_serial_number="MTR-500",
            customer_external_id="CUST-500",
            service_address="500 Energy Plaza",
            grid_region="ERCOT",
            status="ACTIVE",
            updated_at=now,
        )
    )
    await energy_repo.save_meter_reading(
        CanonicalMeterReadingDTO(
            id="ip_mdmr_001",
            tenant_id=tenant_id,
            trace_id="ip_trc_dom_1",
            source_connection_id="ip_conn_itron",
            source_replica_id="ip_rep_001",
            meter_serial_number="MTR-500",
            service_point_id="SP-EXT-001",
            reading_timestamp=now,
            interval_minutes=15,
            kwh_delivered=18.4,
            kwh_received=0.5,
            voltage_avg=241.0,
            quality_flag="VALIDATED",
            recorded_at=now,
        )
    )

    service_point = await energy_repo.get_service_point_by_external_id(tenant_id, "SP-EXT-001")
    assert service_point is not None
    assert service_point.id == "ip_mdms_001"
    assert service_point.tenant_id == tenant_id
    assert service_point.trace_id == "ip_trc_dom_1"
    assert service_point.source_connection_id == "ip_conn_itron"
    assert service_point.source_replica_id == "ip_rep_001"
    assert service_point.service_point_external_id == "SP-EXT-001"
    assert service_point.meter_serial_number == "MTR-500"
    assert service_point.customer_external_id == "CUST-500"
    assert service_point.service_address == "500 Energy Plaza"
    assert service_point.grid_region == "ERCOT"
    assert service_point.status == "ACTIVE"
    assert service_point.updated_at == now

    readings = await energy_repo.list_readings_by_meter(tenant_id, "MTR-500")
    assert len(readings) == 1
    reading = readings[0]
    assert reading.id == "ip_mdmr_001"
    assert reading.tenant_id == tenant_id
    assert reading.trace_id == "ip_trc_dom_1"
    assert reading.source_connection_id == "ip_conn_itron"
    assert reading.source_replica_id == "ip_rep_001"
    assert reading.meter_serial_number == "MTR-500"
    assert reading.service_point_id == "SP-EXT-001"
    assert reading.reading_timestamp == now
    assert reading.interval_minutes == 15
    assert reading.kwh_delivered == 18.4
    assert reading.kwh_received == 0.5
    assert reading.voltage_avg == 241.0
    assert reading.quality_flag == "VALIDATED"
    assert reading.recorded_at == now
