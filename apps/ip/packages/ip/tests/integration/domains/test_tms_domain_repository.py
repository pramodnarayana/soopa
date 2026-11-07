"""Narrow Integration Tests for SqlAlchemyTmsDomainRepository against real PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from database.types import TenantSession
from ip.solutions.domains.tms.canonical import CanonicalCarrierDTO, CanonicalLoadDTO
from ip.solutions.domains.tms.repository import SqlAlchemyTmsDomainRepository

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
            freight_charge_usd=Decimal("3100.25"),
            pickup_scheduled_at=now,
            delivery_scheduled_at=now,
            updated_at=now,
        )
    )

    carrier = await tms_repo.get_carrier_by_scac(tenant_id, "SWFT")
    assert carrier is not None
    assert carrier.id == "ip_tmsc_001"
    assert carrier.tenant_id == tenant_id
    assert carrier.trace_id == "ip_trc_dom_2"
    assert carrier.source_connection_id == "ip_conn_mg"
    assert carrier.source_replica_id == "ip_rep_002"
    assert carrier.scac_code == "SWFT"
    assert carrier.carrier_name == "Swift Transportation"
    assert carrier.dot_number == "DOT-999"
    assert carrier.mc_number == "MC-999"
    assert carrier.safety_rating == "SATISFACTORY"
    assert carrier.status == "ACTIVE"
    assert carrier.updated_at == now

    loads = await tms_repo.list_loads_by_status(tenant_id, "IN_TRANSIT")
    assert len(loads) == 1
    load = loads[0]
    assert load.id == "ip_tmsl_001"
    assert load.tenant_id == tenant_id
    assert load.trace_id == "ip_trc_dom_2"
    assert load.source_connection_id == "ip_conn_mg"
    assert load.source_replica_id == "ip_rep_002"
    assert load.load_reference_number == "LOAD-700"
    assert load.carrier_scac == "SWFT"
    assert load.origin_city == "Houston"
    assert load.origin_state == "TX"
    assert load.destination_city == "Chicago"
    assert load.destination_state == "IL"
    assert load.status == "IN_TRANSIT"
    assert load.total_weight_lbs == 38500.0
    assert isinstance(load.freight_charge_usd, Decimal)
    assert load.freight_charge_usd == Decimal("3100.25")
    assert load.pickup_scheduled_at == now
    assert load.delivery_scheduled_at == now
    assert load.updated_at == now
