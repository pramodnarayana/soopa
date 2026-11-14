"""Pure L3 canonical transformer for SAP IS-U / HANA billing readings (`energy.sap_billing_reading`)."""

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
)


class SapBillingReadingTransformer(TransformerPort):
    """Dedicated pure transformer for SAP IS-U / HANA billing determinants and readings."""

    @property
    def transformation_id(self) -> str:
        return "energy.sap_billing_reading"

    @property
    def transformation_version(self) -> int:
        return 1

    @property
    def target_types(self) -> tuple[str, ...]:
        return (EnergyEntityType.MDM_BILLING_READING.value,)

    def transform(
        self, replica: ReplicaSnapshot, context: TransformationContext
    ) -> TransformationResult:
        payload = replica.data

        reading_id = str(payload.get("reading_id") or replica.record_key or "").strip()
        if not reading_id:
            return TransformationResult(
                rejections=(
                    TransformationRejection(
                        reason=NormalizationRejectionReason.MISSING_REQUIRED_FIELD,
                        field_path="reading_id",
                        detail="Missing required SAP reading_id field.",
                    ),
                )
            )

        serial_number = str(
            payload.get("meter_serial") or payload.get("meter_serial_number") or ""
        ).strip()
        if not serial_number:
            return TransformationResult(
                rejections=(
                    TransformationRejection(
                        reason=NormalizationRejectionReason.MISSING_REQUIRED_FIELD,
                        field_path="meter_serial",
                        detail="Missing required SAP meter_serial field.",
                    ),
                )
            )

        raw_ts = payload.get("reading_timestamp") or payload.get("timestamp")
        if not raw_ts or not str(raw_ts).strip():
            return TransformationResult(
                rejections=(
                    TransformationRejection(
                        reason=NormalizationRejectionReason.MISSING_REQUIRED_FIELD,
                        field_path="reading_timestamp",
                        detail="Missing required SAP reading_timestamp field.",
                    ),
                )
            )
        validated_ts = str(raw_ts).strip()
        if not is_valid_iso_timestamp(validated_ts):
            return TransformationResult(
                rejections=(
                    TransformationRejection(
                        reason=NormalizationRejectionReason.SCHEMA_VALIDATION_FAILED,
                        field_path="reading_timestamp",
                        detail="Invalid ISO-8601 reading timestamp.",
                    ),
                )
            )

        kwh_val = payload.get("kwh_delivered")
        if kwh_val is not None and is_non_finite_number(kwh_val):
            return TransformationResult(
                rejections=(
                    TransformationRejection(
                        reason=NormalizationRejectionReason.QUALITY_RULE_REJECTED,
                        field_path="kwh_delivered",
                        detail="Non-finite measurement rejected for 'kwh_delivered'.",
                    ),
                )
            )

        kwh_delivered = to_finite_float(kwh_val, 0.0)
        quality_flag = str(payload.get("quality_flag") or MeterReadingQualityFlag.VALIDATED.value)
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
                    canonical_type=EnergyEntityType.MDM_BILLING_READING.value,
                    source_id=reading_id,
                    fields={
                        "reading_id": reading_id,
                        "meter_serial_number": serial_number,
                        "service_point_id": sp_id,
                        "reading_timestamp": validated_ts,
                        "kwh_delivered": kwh_delivered,
                        "quality_flag": quality_flag,
                    },
                    references=references,
                ),
            )
        )


__all__ = ["SapBillingReadingTransformer"]
