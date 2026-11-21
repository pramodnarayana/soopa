"""Unit tests for TMS Canonical DTOs and SqlAlchemyTmsDomainRepository Data Mappers."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.engine.domain.normalization.dtos import ReplicaSnapshot, TransformationContext
from ip.engine.domain.normalization.enums import NormalizationRejectionReason
from ip.solutions.domains.tms.canonical import CanonicalCarrierDTO, CanonicalLoadDTO
from ip.solutions.domains.tms.models import TmsCarrierRecord, TmsLoadRecord
from ip.solutions.domains.tms.repository import SqlAlchemyTmsDomainRepository
from ip.solutions.domains.tms.transformers import (
    MercuryGateCarrierTransformer,
    MercuryGateLoadTransformer,
)


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


def test_tms_load_transformer_rejects_non_finite_weight() -> None:
    ctx = TransformationContext(
        tenant_id="ten_01",
        connection_id="conn_01",
        stream="loads",
        trace_id="ip_trc_02",
    )
    transformer = MercuryGateLoadTransformer()
    for bad_val in ("nan", float("inf"), 10**400):
        res = transformer.transform(
            ReplicaSnapshot(
                id="rep_tms_nan",
                connection_id="conn_01",
                stream="loads",
                record_key="LD-100",
                version=1,
                data={"load_id": "LD-100", "total_weight_lbs": bad_val},
            ),
            ctx,
        )
        assert not res.drafts
        assert len(res.rejections) == 1
        assert res.rejections[0].reason == NormalizationRejectionReason.QUALITY_RULE_REJECTED


def test_tms_load_transformer_rejects_non_finite_freight_charge() -> None:
    ctx = TransformationContext(
        tenant_id="ten_01",
        connection_id="conn_01",
        stream="loads",
        trace_id="ip_trc_02",
    )
    transformer = MercuryGateLoadTransformer()
    for bad_val in ("-inf", float("nan"), -(10**400)):
        res = transformer.transform(
            ReplicaSnapshot(
                id="rep_tms_nan",
                connection_id="conn_01",
                stream="loads",
                record_key="LD-100",
                version=1,
                data={"load_id": "LD-100", "freight_charge_usd": bad_val},
            ),
            ctx,
        )
        assert not res.drafts
        assert len(res.rejections) == 1
        assert res.rejections[0].reason == NormalizationRejectionReason.QUALITY_RULE_REJECTED


def test_mercury_gate_load_transformer_maps_valid_load() -> None:
    ctx = TransformationContext(
        tenant_id="ten_01",
        connection_id="conn_01",
        stream="loads",
        trace_id="ip_trc_02",
    )
    transformer = MercuryGateLoadTransformer()
    assert transformer.transformation_id == "tms.mercury_gate_load"
    assert transformer.transformation_version == 2

    res = transformer.transform(
        ReplicaSnapshot(
            id="rep_tms_01",
            connection_id="conn_01",
            stream="loads",
            record_key="LD-100",
            version=1,
            data={
                "load_id": "LD-100",
                "carrier_scac": "JBHT",
                "origin_city": "Dallas",
                "origin_state": "TX",
                "destination_city": "Atlanta",
                "destination_state": "GA",
                "status": "IN_TRANSIT",
                "total_weight_lbs": 42000.0,
                "freight_charge_usd": 2850.0,
            },
        ),
        ctx,
    )
    assert not res.rejections
    assert len(res.drafts) == 1
    draft = res.drafts[0]
    assert draft.fields["load_reference_number"] == "LD-100"
    assert draft.fields["lane_code"] == "TX->GA"
    assert draft.fields["total_weight_lbs"] == 42000.0


def test_mercury_gate_carrier_transformer_maps_valid_carrier() -> None:
    ctx = TransformationContext(
        tenant_id="ten_01",
        connection_id="conn_01",
        stream="carriers",
        trace_id="ip_trc_03",
    )
    transformer = MercuryGateCarrierTransformer()
    assert transformer.transformation_id == "tms.mercury_gate_carrier"
    assert transformer.transformation_version == 1

    res = transformer.transform(
        ReplicaSnapshot(
            id="rep_tms_02",
            connection_id="conn_01",
            stream="carriers",
            record_key="JBHT",
            version=1,
            data={
                "scac": "JBHT",
                "carrier_name": "J.B. Hunt Transport",
                "dot_number": "DOT-123456",
                "mc_number": "MC-654321",
                "status": "ACTIVE",
            },
        ),
        ctx,
    )
    assert not res.rejections
    assert len(res.drafts) == 1
    draft = res.drafts[0]
    assert draft.fields["scac_code"] == "JBHT"
    assert draft.fields["carrier_name"] == "J.B. Hunt Transport"
