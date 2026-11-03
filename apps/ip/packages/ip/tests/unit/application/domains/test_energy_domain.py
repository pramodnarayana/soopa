"""Unit tests for Energy MDM Canonical DTOs and SqlAlchemyEnergyDomainRepository Data Mappers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ip.engine.domain.normalization.enums import NormalizationRejectionReason
from ip.engine.domain.normalization.transformation import ReplicaSnapshot, TransformationContext
from ip.solutions.domains.energy.canonical import (
    CanonicalMeterReadingDTO,
    CanonicalServicePointDTO,
)
from ip.solutions.domains.energy.models import (
    MdmMeterReadingRecord,
    MdmServicePointRecord,
)
from ip.solutions.domains.energy.repository import SqlAlchemyEnergyDomainRepository
from ip.solutions.domains.energy.transformers import (
    AmiMeterReadingTransformerV1,
    AmiMeterReadingTransformerV2,
)
from ip.solutions.domains.energy.writers import (
    _parse_float,
    _parse_iso_datetime,
    _parse_optional_float,
)
from ip.solutions.domains.numeric import (
    is_non_finite_number,
    to_finite_float,
    to_finite_int,
    to_optional_finite_float,
)


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


def test_energy_meter_reading_transformer_rejects_invalid_timestamp_and_non_finite_metrics() -> (
    None
):
    ctx = TransformationContext(
        tenant_id="ten_01",
        connection_id="conn_01",
        stream="meter_reads",
        trace_id="ip_trc_01",
    )
    v1 = AmiMeterReadingTransformerV1()
    v2 = AmiMeterReadingTransformerV2()

    bad_ts_res = v1.transform(
        ReplicaSnapshot(
            id="rep_bad_ts",
            connection_id="conn_01",
            stream="meter_reads",
            record_key="MTR-1:bad",
            version=1,
            data={"meter_serial": "MTR-1", "timestamp": "not-a-timestamp", "kwh_delivered": 10.5},
        ),
        ctx,
    )
    assert not bad_ts_res.drafts
    assert len(bad_ts_res.rejections) == 1
    assert bad_ts_res.rejections[0].reason == NormalizationRejectionReason.SCHEMA_VALIDATION_FAILED

    with pytest.raises(ValueError, match="Invalid ISO-8601 timestamp"):
        _parse_iso_datetime("not-a-timestamp")

    for field_name, bad_val in (
        ("kwh_delivered", "nan"),
        ("kwh_delivered", float("inf")),
        ("kwh_delivered", 10**400),
        ("kwh_received", "-inf"),
        ("kwh_received", float("nan")),
        ("kwh_received", -(10**400)),
    ):
        non_finite_res = v2.transform(
            ReplicaSnapshot(
                id="rep_nan",
                connection_id="conn_01",
                stream="meter_reads",
                record_key="MTR-1:2026-10-29T00:00:00Z",
                version=1,
                data={
                    "meter_serial": "MTR-1",
                    "timestamp": "2026-10-29T00:00:00Z",
                    field_name: bad_val,
                },
            ),
            ctx,
        )
        assert not non_finite_res.drafts
        assert len(non_finite_res.rejections) == 1
        assert (
            non_finite_res.rejections[0].reason
            == NormalizationRejectionReason.QUALITY_RULE_REJECTED
        )

    valid_with_non_finite_optional = v2.transform(
        ReplicaSnapshot(
            id="rep_opt_nan",
            connection_id="conn_01",
            stream="meter_reads",
            record_key="MTR-1:2026-10-29T00:15:00Z",
            version=1,
            data={
                "meter_serial": "MTR-1",
                "timestamp": "2026-10-29T00:15:00Z",
                "kwh_delivered": 12.5,
                "kwh_received": 2.5,
                "voltage_avg": 10**400,
                "interval_minutes": float("inf"),
            },
        ),
        ctx,
    )
    assert len(valid_with_non_finite_optional.drafts) == 1
    draft_fields = valid_with_non_finite_optional.drafts[0].fields
    assert draft_fields["voltage_avg"] is None
    assert draft_fields["interval_minutes"] == 15
    assert draft_fields["net_kwh"] == 10.0

    overflow_diff_res = v2.transform(
        ReplicaSnapshot(
            id="rep_overflow_diff",
            connection_id="conn_01",
            stream="meter_reads",
            record_key="MTR-1:2026-10-29T00:30:00Z",
            version=1,
            data={
                "meter_serial": "MTR-1",
                "timestamp": "2026-10-29T00:30:00Z",
                "kwh_delivered": 1e308,
                "kwh_received": -1e308,
            },
        ),
        ctx,
    )
    assert len(overflow_diff_res.drafts) == 1
    assert overflow_diff_res.drafts[0].fields["net_kwh"] is None

    assert is_non_finite_number(10**400) is True
    assert to_optional_finite_float(10**400) is None
    assert to_finite_float(10**400, 0.0) == 0.0
    assert to_finite_int(float("nan"), 15) == 15
    assert _parse_optional_float(10**400) is None
    assert _parse_float(10**400, 0.0) == 0.0
