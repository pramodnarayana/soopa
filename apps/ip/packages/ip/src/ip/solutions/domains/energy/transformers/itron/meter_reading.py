"""Pure L3 canonical transformers for Itron OpenWay / ChoiceConnect AMI meter readings (`energy.itron_meter_reading`)."""

from __future__ import annotations

from ip.engine.domain.normalization.enums import NormalizationRejectionReason
from ip.engine.domain.normalization.transformation import (
    CanonicalDraft,
    ReplicaSnapshot,
    SourceReference,
    TransformationContext,
    TransformationRejection,
    TransformationResult,
)
from ip.engine.ports.outbound.transformer_port import TransformerPort
from ip.solutions.domains.energy.canonical import (
    EnergyEntityType,
    MeterReadingQualityFlag,
)
from ip.solutions.domains.energy.transformers.common import is_valid_iso_timestamp
from ip.solutions.domains.numeric import (
    is_non_finite_number,
    to_finite_float,
    to_finite_int,
    to_optional_finite_float,
)


class ItronMeterReadingTransformerV1(TransformerPort):
    """Dedicated pure transformer for Itron OpenWay / ChoiceConnect AMI meter reading head-end exports."""

    @property
    def transformation_id(self) -> str:
        return "energy.itron_meter_reading"

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
        serial_number = str(payload.get("serial_number") or "").strip()
        if not serial_number:
            return TransformationResult(
                rejections=(
                    TransformationRejection(
                        reason=NormalizationRejectionReason.MISSING_REQUIRED_FIELD,
                        field_path="serial_number",
                        detail="Missing required Itron serial_number field.",
                    ),
                )
            )

        raw_ts = payload.get("last_reading_time")
        if not raw_ts or not str(raw_ts).strip():
            return TransformationResult(
                rejections=(
                    TransformationRejection(
                        reason=NormalizationRejectionReason.MISSING_REQUIRED_FIELD,
                        field_path="last_reading_time",
                        detail="Missing required Itron last_reading_time field.",
                    ),
                )
            )
        validated_ts = str(raw_ts).strip()
        if not is_valid_iso_timestamp(validated_ts):
            return TransformationResult(
                rejections=(
                    TransformationRejection(
                        reason=NormalizationRejectionReason.SCHEMA_VALIDATION_FAILED,
                        field_path="last_reading_time",
                        detail="Invalid ISO-8601 reading timestamp.",
                    ),
                )
            )

        for metric_field in ("kwh_delivered", "kwh_received"):
            if is_non_finite_number(payload.get(metric_field)):
                return TransformationResult(
                    rejections=(
                        TransformationRejection(
                            reason=NormalizationRejectionReason.QUALITY_RULE_REJECTED,
                            field_path=metric_field,
                            detail=f"Non-finite measurement rejected for '{metric_field}'.",
                        ),
                    )
                )

        kwh_delivered = to_finite_float(payload.get("kwh_delivered"), 0.0)
        kwh_received = to_finite_float(payload.get("kwh_received"), 0.0)
        interval_minutes = to_finite_int(payload.get("interval_minutes"), 15)
        voltage_avg = to_optional_finite_float(payload.get("voltage_avg"))
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
                    source_id=replica.record_key or f"{serial_number}:{validated_ts}",
                    fields={
                        "meter_serial_number": serial_number,
                        "service_point_id": sp_id,
                        "reading_timestamp": validated_ts,
                        "interval_minutes": interval_minutes,
                        "kwh_delivered": kwh_delivered,
                        "kwh_received": kwh_received,
                        "voltage_avg": voltage_avg,
                        "quality_flag": quality_flag,
                    },
                    references=references,
                ),
            )
        )
