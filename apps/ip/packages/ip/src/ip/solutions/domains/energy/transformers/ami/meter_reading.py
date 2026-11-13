"""Pure L3 canonical transformers for AMI interval meter readings (`energy.ami_meter_reading`)."""

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
        meter_serial = str(payload.get("meter_serial") or payload.get("meter_id") or "").strip()
        if not meter_serial:
            return TransformationResult(
                rejections=(
                    TransformationRejection(
                        reason=NormalizationRejectionReason.MISSING_REQUIRED_FIELD,
                        field_path="meter_serial",
                        detail="Missing required meter_serial or meter_id field.",
                    ),
                )
            )

        raw_ts = payload.get("timestamp")
        if not raw_ts or not str(raw_ts).strip():
            return TransformationResult(
                rejections=(
                    TransformationRejection(
                        reason=NormalizationRejectionReason.MISSING_REQUIRED_FIELD,
                        field_path="timestamp",
                        detail="Missing required timestamp field.",
                    ),
                )
            )
        validated_ts = str(raw_ts).strip()
        if not is_valid_iso_timestamp(validated_ts):
            return TransformationResult(
                rejections=(
                    TransformationRejection(
                        reason=NormalizationRejectionReason.SCHEMA_VALIDATION_FAILED,
                        field_path="timestamp",
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
                    source_id=replica.record_key or f"{meter_serial}:{validated_ts}",
                    fields={
                        "meter_serial_number": meter_serial,
                        "service_point_id": sp_id,
                        "reading_timestamp": validated_ts,
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
        voltage_avg = to_optional_finite_float(payload.get("voltage_avg"))
        kwh_delivered = to_finite_float(base_draft.fields.get("kwh_delivered"), 0.0)
        kwh_received = to_finite_float(base_draft.fields.get("kwh_received"), 0.0)
        net_kwh = to_optional_finite_float(round(kwh_delivered - kwh_received, 4))

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
