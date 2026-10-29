"""Pure L3 canonical transformers for the Energy Smart Grid domain (`mdm_meter_readings`, `mdm_service_points`)."""

from __future__ import annotations

from ip.application.domains.energy.canonical import (
    EnergyEntityType,
    MeterReadingQualityFlag,
    ServicePointStatus,
)
from ip.engine.domain.enums import NormalizationRejectionReason
from ip.engine.domain.normalization import (
    CanonicalDraft,
    ReplicaSnapshot,
    SourceReference,
    TransformationContext,
    TransformationRejection,
    TransformationResult,
)
from ip.engine.ports.outbound.transformer_port import TransformerPort


def _to_float(val: object, default: float = 0.0) -> float:
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val))
    except (ValueError, TypeError):
        return default


def _to_optional_float(val: object) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val))
    except (ValueError, TypeError):
        return None


def _to_int(val: object, default: int = 15) -> int:
    if val is None:
        return default
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    try:
        return int(str(val))
    except (ValueError, TypeError):
        return default


class AmiMeterReadingTransformerV1(TransformerPort):
    """Version 1 pure transformer for AMI Smart Grid interval meter readings."""

    @property
    def transformation_id(self) -> str:
        return "energy.ami_meter_reading"

    @property
    def transformation_version(self) -> int:
        return 1

    @property
    def target_types(self) -> tuple[str, ...]:
        return (EnergyEntityType.MDM_METER_READING.value,)

    def transform(
        self, replica: ReplicaSnapshot, context: TransformationContext
    ) -> TransformationResult:
        payload = replica.data
        meter_serial = str(
            payload.get("meter_serial")
            or payload.get("serial_number")
            or payload.get("meter_id")
            or payload.get("id")
            or ""
        ).strip()
        if not meter_serial:
            return TransformationResult(
                rejections=(
                    TransformationRejection(
                        reason=NormalizationRejectionReason.MISSING_REQUIRED_FIELD,
                        field_path="meter_serial",
                        detail="Missing required meter_serial / meter_id field.",
                    ),
                )
            )

        raw_ts = payload.get("timestamp") or payload.get("last_reading_time")
        if not raw_ts or not str(raw_ts).strip():
            return TransformationResult(
                rejections=(
                    TransformationRejection(
                        reason=NormalizationRejectionReason.MISSING_REQUIRED_FIELD,
                        field_path="timestamp",
                        detail="Missing required timestamp / last_reading_time field.",
                    ),
                )
            )

        kwh_delivered = _to_float(payload.get("kwh_delivered"), 0.0)
        kwh_received = _to_float(payload.get("kwh_received"), 0.0)
        interval_minutes = _to_int(payload.get("interval_minutes"), 15)
        quality_flag = str(payload.get("quality") or MeterReadingQualityFlag.VALIDATED.value)
        sp_id_raw = payload.get("service_point_id")
        sp_id = str(sp_id_raw).strip() if sp_id_raw is not None and str(sp_id_raw).strip() else None

        references: tuple[SourceReference, ...] = ()
        if sp_id is not None:
            references = (
                SourceReference(
                    field_name="service_point_id",
                    target_canonical_type=EnergyEntityType.MDM_SERVICE_POINT.value,
                    target_source_id=sp_id,
                ),
            )

        return TransformationResult(
            drafts=(
                CanonicalDraft(
                    canonical_type=EnergyEntityType.MDM_METER_READING.value,
                    source_id=replica.record_key or f"{meter_serial}:{raw_ts}",
                    fields={
                        "meter_serial_number": meter_serial,
                        "service_point_id": sp_id,
                        "reading_timestamp": str(raw_ts),
                        "interval_minutes": interval_minutes,
                        "kwh_delivered": kwh_delivered,
                        "kwh_received": kwh_received,
                        "quality_flag": quality_flag,
                    },
                    references=references,
                ),
            )
        )


class AmiMeterReadingTransformerV2(TransformerPort):
    """Version 2 pure transformer for AMI Smart Grid interval meter readings (adds voltage_avg and net_kwh)."""

    @property
    def transformation_id(self) -> str:
        return "energy.ami_meter_reading"

    @property
    def transformation_version(self) -> int:
        return 2

    @property
    def target_types(self) -> tuple[str, ...]:
        return (EnergyEntityType.MDM_METER_READING.value,)

    def transform(
        self, replica: ReplicaSnapshot, context: TransformationContext
    ) -> TransformationResult:
        v1_res = AmiMeterReadingTransformerV1().transform(replica, context)
        if v1_res.rejections or not v1_res.drafts:
            return v1_res

        base_draft = v1_res.drafts[0]
        payload = replica.data
        voltage_avg = _to_optional_float(payload.get("voltage_avg"))
        kwh_delivered = _to_float(base_draft.fields.get("kwh_delivered"), 0.0)
        kwh_received = _to_float(base_draft.fields.get("kwh_received"), 0.0)
        net_kwh = round(kwh_delivered - kwh_received, 4)

        updated_fields = dict(base_draft.fields)
        updated_fields["voltage_avg"] = voltage_avg
        updated_fields["net_kwh"] = net_kwh

        return TransformationResult(
            drafts=(
                CanonicalDraft(
                    canonical_type=base_draft.canonical_type,
                    source_id=base_draft.source_id,
                    fields=updated_fields,
                    references=base_draft.references,
                    extensions={"schema_revision": "v2"},
                ),
            )
        )


class AmiServicePointTransformerV1(TransformerPort):
    """Version 1 pure transformer for AMI Smart Grid service points."""

    @property
    def transformation_id(self) -> str:
        return "energy.ami_service_point"

    @property
    def transformation_version(self) -> int:
        return 1

    @property
    def target_types(self) -> tuple[str, ...]:
        return (EnergyEntityType.MDM_SERVICE_POINT.value,)

    def transform(
        self, replica: ReplicaSnapshot, context: TransformationContext
    ) -> TransformationResult:
        payload = replica.data
        sp_id = str(
            payload.get("service_point_id") or payload.get("id") or replica.record_key or ""
        ).strip()
        if not sp_id:
            return TransformationResult(
                rejections=(
                    TransformationRejection(
                        reason=NormalizationRejectionReason.MISSING_REQUIRED_FIELD,
                        field_path="id",
                        detail="Missing required service point identifier.",
                    ),
                )
            )
        return TransformationResult(
            drafts=(
                CanonicalDraft(
                    canonical_type=EnergyEntityType.MDM_SERVICE_POINT.value,
                    source_id=sp_id,
                    fields={
                        "service_point_external_id": sp_id,
                        "meter_serial_number": payload.get("meter_id"),
                        "customer_external_id": payload.get("customer_id"),
                        "service_address": payload.get("address"),
                        "status": str(payload.get("status") or ServicePointStatus.ACTIVE.value),
                    },
                ),
            )
        )


__all__ = [
    "AmiMeterReadingTransformerV1",
    "AmiMeterReadingTransformerV2",
    "AmiServicePointTransformerV1",
]
