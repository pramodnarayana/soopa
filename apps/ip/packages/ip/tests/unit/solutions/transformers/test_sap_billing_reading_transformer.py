"""Zero-mock unit tests for SapBillingReadingTransformer."""

from __future__ import annotations

from ip.engine.domain.normalization.enums import NormalizationRejectionReason
from ip.engine.domain.normalization.transformation import (
    ReplicaSnapshot,
    TransformationContext,
)
from ip.solutions.domains.energy.canonical import EnergyEntityType
from ip.solutions.domains.energy.transformers.sap.billing_reading import (
    SapBillingReadingTransformer,
)


def _make_context() -> TransformationContext:
    return TransformationContext(
        connection_id="conn_sap_1",
        stream="billing_readings",
        tenant_id="tenant_utility_1",
        trace_id="trace_test_1",
        correlation_id="corr_test_1",
    )


def test_sap_transformer_transforms_valid_payload() -> None:
    transformer = SapBillingReadingTransformer()
    snapshot = ReplicaSnapshot(
        id="rep_1",
        connection_id="conn_sap_1",
        stream="billing_readings",
        record_key="BILL-RDG-1001",
        version=1,
        data={
            "reading_id": "BILL-RDG-1001",
            "meter_serial": "MTR-5001",
            "kwh_delivered": 14.5,
            "reading_timestamp": "2026-11-13T10:00:00Z",
            "service_point_id": "SP-1001",
        },
    )

    result = transformer.transform(snapshot, _make_context())

    assert len(result.rejections) == 0
    assert len(result.drafts) == 1
    draft = result.drafts[0]
    assert draft.canonical_type == EnergyEntityType.MDM_BILLING_READING.value
    assert draft.source_id == "BILL-RDG-1001"
    assert draft.fields["reading_id"] == "BILL-RDG-1001"
    assert draft.fields["meter_serial_number"] == "MTR-5001"
    assert draft.fields["kwh_delivered"] == 14.5
    assert draft.fields["reading_timestamp"] == "2026-11-13T10:00:00Z"
    assert draft.fields["service_point_id"] == "SP-1001"
    assert draft.fields["quality_flag"] == "VALIDATED"
    assert len(draft.references) == 1
    assert draft.references[0].target_canonical_type == EnergyEntityType.MDM_SERVICE_POINT.value
    assert draft.references[0].target_source_id == "SP-1001"


def test_sap_transformer_rejects_missing_reading_id() -> None:
    transformer = SapBillingReadingTransformer()
    snapshot = ReplicaSnapshot(
        id="rep_1",
        connection_id="conn_sap_1",
        stream="billing_readings",
        record_key="",
        version=1,
        data={
            "meter_serial": "MTR-5001",
            "kwh_delivered": 14.5,
            "reading_timestamp": "2026-11-13T10:00:00Z",
        },
    )

    result = transformer.transform(snapshot, _make_context())
    assert len(result.drafts) == 0
    assert len(result.rejections) == 1
    assert result.rejections[0].reason == NormalizationRejectionReason.MISSING_REQUIRED_FIELD
    assert result.rejections[0].field_path == "reading_id"


def test_sap_transformer_rejects_missing_meter_serial() -> None:
    transformer = SapBillingReadingTransformer()
    snapshot = ReplicaSnapshot(
        id="rep_1",
        connection_id="conn_sap_1",
        stream="billing_readings",
        record_key="BILL-1001",
        version=1,
        data={
            "reading_id": "BILL-1001",
            "kwh_delivered": 14.5,
            "reading_timestamp": "2026-11-13T10:00:00Z",
        },
    )

    result = transformer.transform(snapshot, _make_context())
    assert len(result.drafts) == 0
    assert len(result.rejections) == 1
    assert result.rejections[0].reason == NormalizationRejectionReason.MISSING_REQUIRED_FIELD
    assert result.rejections[0].field_path == "meter_serial"


def test_sap_transformer_rejects_invalid_timestamp() -> None:
    transformer = SapBillingReadingTransformer()
    snapshot = ReplicaSnapshot(
        id="rep_1",
        connection_id="conn_sap_1",
        stream="billing_readings",
        record_key="BILL-1001",
        version=1,
        data={
            "reading_id": "BILL-1001",
            "meter_serial": "MTR-5001",
            "kwh_delivered": 14.5,
            "reading_timestamp": "not-a-valid-date",
        },
    )

    result = transformer.transform(snapshot, _make_context())
    assert len(result.drafts) == 0
    assert len(result.rejections) == 1
    assert result.rejections[0].reason == NormalizationRejectionReason.SCHEMA_VALIDATION_FAILED
    assert result.rejections[0].field_path == "reading_timestamp"


def test_sap_transformer_rejects_nan_kwh() -> None:
    transformer = SapBillingReadingTransformer()
    snapshot = ReplicaSnapshot(
        id="rep_1",
        connection_id="conn_sap_1",
        stream="billing_readings",
        record_key="BILL-1001",
        version=1,
        data={
            "reading_id": "BILL-1001",
            "meter_serial": "MTR-5001",
            "kwh_delivered": float("nan"),
            "reading_timestamp": "2026-11-13T10:00:00Z",
        },
    )

    result = transformer.transform(snapshot, _make_context())
    assert len(result.drafts) == 0
    assert len(result.rejections) == 1
    assert result.rejections[0].reason == NormalizationRejectionReason.QUALITY_RULE_REJECTED
    assert result.rejections[0].field_path == "kwh_delivered"
