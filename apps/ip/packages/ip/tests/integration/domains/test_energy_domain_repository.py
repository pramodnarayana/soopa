"""Narrow Integration Tests for SqlAlchemyEnergyDomainRepository against real PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from database.types import TenantSession
from ip.application.domains.energy.canonical import (
    CanonicalMeterReadingDTO,
    CanonicalServicePointDTO,
)
from ip.application.domains.energy.repository import SqlAlchemyEnergyDomainRepository

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

    readings = await energy_repo.list_readings_by_meter(tenant_id, "MTR-500")
    assert len(readings) == 1
    assert readings[0].kwh_delivered == 18.4
