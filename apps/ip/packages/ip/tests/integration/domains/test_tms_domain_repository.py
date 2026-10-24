"""Narrow Integration Tests for SqlAlchemyTmsDomainRepository against real PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from database.types import TenantSession
from ip.application.domains.tms.canonical import CanonicalCarrierDTO, CanonicalLoadDTO
from ip.application.domains.tms.repository import SqlAlchemyTmsDomainRepository

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_canonical_tms_domain_repository(
    tenant_session: TenantSession,
) -> None:
    tms_repo = SqlAlchemyTmsDomainRepository(tenant_session)
    tenant_id = "ten_dp_tms"
    now = datetime.now(UTC)

    await tms_repo.save_carrier(
        CanonicalCarrierDTO(
            id="ip_tmsc_001",
            tenant_id=tenant_id,
            trace_id="ip_trc_dom_2",
            source_connection_id="ip_conn_mg",
            source_replica_id="ip_rep_002",
            scac_code="SWFT",
            carrier_name="Swift Transportation",
            dot_number="DOT-999",
            mc_number="MC-999",
            safety_rating="SATISFACTORY",
            status="ACTIVE",
            updated_at=now,
        )
    )
    await tms_repo.save_load(
        CanonicalLoadDTO(
            id="ip_tmsl_001",
            tenant_id=tenant_id,
            trace_id="ip_trc_dom_2",
            source_connection_id="ip_conn_mg",
            source_replica_id="ip_rep_002",
            load_reference_number="LOAD-700",
            carrier_scac="SWFT",
            origin_city="Houston",
            origin_state="TX",
            destination_city="Chicago",
            destination_state="IL",
            status="IN_TRANSIT",
            total_weight_lbs=38500.0,
            freight_charge_usd=3100.0,
            pickup_scheduled_at=now,
            delivery_scheduled_at=now,
            updated_at=now,
        )
    )

    loads = await tms_repo.list_loads_by_status(tenant_id, "IN_TRANSIT")
    assert len(loads) == 1
    assert loads[0].load_reference_number == "LOAD-700"
