"""Unit tests for TMS Canonical DTOs and SqlAlchemyTmsDomainRepository Data Mappers."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.application.domains.tms.canonical import CanonicalCarrierDTO, CanonicalLoadDTO
from ip.application.domains.tms.models import TmsCarrierRecord, TmsLoadRecord
from ip.application.domains.tms.repository import SqlAlchemyTmsDomainRepository


def test_canonical_tms_dtos_are_immutable() -> None:
    now = datetime.now(UTC)

    load = CanonicalLoadDTO(
        id="tms_load_01",
        tenant_id="ten_01",
        trace_id="ip_trc_02",
        source_connection_id="ip_conn_mg",
        source_replica_id="ip_rep_02",
        load_reference_number="LD-2026-999",
        carrier_scac="JBHT",
        origin_city="Dallas",
        origin_state="TX",
        destination_city="Atlanta",
        destination_state="GA",
        status="IN_TRANSIT",
        total_weight_lbs=42000.0,
        freight_charge_usd=2850.0,
        pickup_scheduled_at=now,
        delivery_scheduled_at=now,
        updated_at=now,
    )
    assert load.carrier_scac == "JBHT"

    carrier = CanonicalCarrierDTO(
        id="tms_car_01",
        tenant_id="ten_01",
        trace_id="ip_trc_02",
        source_connection_id="ip_conn_mg",
        source_replica_id="ip_rep_02",
        scac_code="JBHT",
        carrier_name="J.B. Hunt Transport",
        dot_number="DOT-123456",
        mc_number="MC-654321",
        safety_rating="SATISFACTORY",
        status="ACTIVE",
        updated_at=now,
    )
    assert carrier.scac_code == "JBHT"


def test_tms_domain_repository_mappers() -> None:
    now = datetime.now(UTC)
    load_orm = TmsLoadRecord(
        id="tms_l_1",
        tenant_id="ten_01",
        trace_id="trc_01",
        correlation_id=None,
        parent_trace_id=None,
        original_trace_id=None,
        replay_count=0,
        source_connection_id="conn_1",
        source_replica_id="rep_1",
        load_reference_number="REF-1",
        carrier_scac="SCAC",
        origin_city="Austin",
        origin_state="TX",
        destination_city="Denver",
        destination_state="CO",
        status="TENDERED",
        total_weight_lbs=10000.0,
        freight_charge_usd=1500.0,
        pickup_scheduled_at=now,
        delivery_scheduled_at=now,
        updated_at=now,
    )
    load_dto: CanonicalLoadDTO = SqlAlchemyTmsDomainRepository._to_load_dto(load_orm)
    assert load_dto.load_reference_number == "REF-1"

    carrier_orm = TmsCarrierRecord(
        id="tms_c_1",
        tenant_id="ten_01",
        trace_id="trc_01",
        correlation_id=None,
        parent_trace_id=None,
        original_trace_id=None,
        replay_count=0,
        source_connection_id="conn_1",
        source_replica_id="rep_1",
        scac_code="SCAC",
        carrier_name="Carrier One",
        dot_number="123",
        mc_number="456",
        safety_rating="SATISFACTORY",
        status="ACTIVE",
        updated_at=now,
    )
    carrier_dto: CanonicalCarrierDTO = SqlAlchemyTmsDomainRepository._to_carrier_dto(carrier_orm)
    assert carrier_dto.scac_code == "SCAC"
