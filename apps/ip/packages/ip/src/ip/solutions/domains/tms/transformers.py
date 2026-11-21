"""Pure L3 canonical transformers for the TMS Logistics domain (`tms_loads`, `tms_carriers`)."""

from __future__ import annotations

from ip.engine.domain.normalization.dtos import (
    CanonicalDraft,
    ReplicaSnapshot,
    TransformationContext,
    TransformationRejection,
    TransformationResult,
)
from ip.engine.domain.normalization.enums import NormalizationRejectionReason
from ip.engine.ports.outbound.transformer_port import TransformerPort
from ip.solutions.domains.numeric import is_non_finite_number, to_finite_float
from ip.solutions.domains.tms.canonical import TmsEntityType


class MercuryGateLoadTransformer(TransformerPort):
    """Pure transformer for MercuryGate TMS freight loads."""

    @property
    def transformation_id(self) -> str:
        return "tms.mercury_gate_load"

    @property
    def transformation_version(self) -> int:
        return 2

    @property
    def target_types(self) -> tuple[str, ...]:
        return (TmsEntityType.TMS_LOAD.value,)

    def transform(
        self, replica: ReplicaSnapshot, context: TransformationContext
    ) -> TransformationResult:
        payload = replica.data
        load_ref = str(
            payload.get("load_id")
            or payload.get("reference_number")
            or payload.get("id")
            or replica.record_key
            or ""
        ).strip()
        if not load_ref:
            return TransformationResult(
                rejections=(
                    TransformationRejection(
                        reason=NormalizationRejectionReason.MISSING_REQUIRED_FIELD,
                        field_path="reference_number",
                        detail="Missing required load_id or reference_number.",
                    ),
                )
            )

        for metric_field in ("total_weight_lbs", "freight_charge_usd"):
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

        weight_lbs = to_finite_float(payload.get("total_weight_lbs"), 0.0)
        charge_usd = to_finite_float(payload.get("freight_charge_usd"), 0.0)
        origin_state = str(payload.get("origin_state") or "NA")
        dest_state = str(payload.get("destination_state") or "NA")
        lane_code = f"{origin_state}->{dest_state}"

        return TransformationResult(
            drafts=(
                CanonicalDraft(
                    canonical_type=TmsEntityType.TMS_LOAD.value,
                    source_id=load_ref,
                    fields={
                        "load_reference_number": load_ref,
                        "carrier_scac": payload.get("carrier_scac"),
                        "origin_city": str(payload.get("origin_city") or "UNKNOWN"),
                        "origin_state": origin_state,
                        "destination_city": str(payload.get("destination_city") or "UNKNOWN"),
                        "destination_state": dest_state,
                        "lane_code": lane_code,
                        "status": str(payload.get("status") or "TENDERED"),
                        "total_weight_lbs": weight_lbs,
                        "freight_charge_usd": charge_usd,
                    },
                    extensions={"schema_revision": "v2"},
                ),
            )
        )


class MercuryGateCarrierTransformer(TransformerPort):
    """Pure transformer for MercuryGate TMS carriers."""

    @property
    def transformation_id(self) -> str:
        return "tms.mercury_gate_carrier"

    @property
    def transformation_version(self) -> int:
        return 1

    @property
    def target_types(self) -> tuple[str, ...]:
        return (TmsEntityType.TMS_CARRIER.value,)

    def transform(
        self, replica: ReplicaSnapshot, context: TransformationContext
    ) -> TransformationResult:
        payload = replica.data
        scac = str(
            payload.get("scac") or payload.get("scac_code") or replica.record_key or ""
        ).strip()
        if not scac:
            return TransformationResult(
                rejections=(
                    TransformationRejection(
                        reason=NormalizationRejectionReason.MISSING_REQUIRED_FIELD,
                        field_path="scac",
                        detail="Missing required carrier SCAC code.",
                    ),
                )
            )
        return TransformationResult(
            drafts=(
                CanonicalDraft(
                    canonical_type=TmsEntityType.TMS_CARRIER.value,
                    source_id=scac,
                    fields={
                        "scac_code": scac,
                        "carrier_name": str(payload.get("carrier_name") or scac),
                        "dot_number": payload.get("dot_number"),
                        "mc_number": payload.get("mc_number"),
                        "status": str(payload.get("status") or "ACTIVE"),
                    },
                ),
            )
        )


__all__ = [
    "MercuryGateCarrierTransformer",
    "MercuryGateLoadTransformer",
]
