"""Pure L3 canonical transformers for the TMS Logistics domain (`tms_loads`, `tms_carriers`)."""

from __future__ import annotations

from ip.application.domains.tms.canonical import TmsEntityType
from ip.engine.domain.enums import NormalizationRejectionReason
from ip.engine.domain.normalization import (
    CanonicalDraft,
    ReplicaSnapshot,
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


class MercuryGateLoadTransformerV1(TransformerPort):
    """Version 1 pure transformer for MercuryGate TMS freight loads."""

    @property
    def transformation_id(self) -> str:
        return "tms.mercury_gate_load"

    @property
    def transformation_version(self) -> int:
        return 1

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

        weight_lbs = _to_float(payload.get("total_weight_lbs"), 0.0)
        charge_usd = _to_float(payload.get("freight_charge_usd"), 0.0)

        return TransformationResult(
            drafts=(
                CanonicalDraft(
                    canonical_type=TmsEntityType.TMS_LOAD.value,
                    source_id=load_ref,
                    fields={
                        "load_reference_number": load_ref,
                        "carrier_scac": payload.get("carrier_scac"),
                        "origin_city": str(payload.get("origin_city") or "UNKNOWN"),
                        "origin_state": str(payload.get("origin_state") or "NA"),
                        "destination_city": str(payload.get("destination_city") or "UNKNOWN"),
                        "destination_state": str(payload.get("destination_state") or "NA"),
                        "status": str(payload.get("status") or "TENDERED"),
                        "total_weight_lbs": weight_lbs,
                        "freight_charge_usd": charge_usd,
                    },
                ),
            )
        )


class MercuryGateLoadTransformerV2(TransformerPort):
    """Version 2 pure transformer for MercuryGate TMS freight loads (adds fuel surcharge & normalized lane key)."""

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
        v1_res = MercuryGateLoadTransformerV1().transform(replica, context)
        if v1_res.rejections or not v1_res.drafts:
            return v1_res

        base_draft = v1_res.drafts[0]
        origin_state = str(base_draft.fields.get("origin_state") or "NA")
        dest_state = str(base_draft.fields.get("destination_state") or "NA")
        updated_fields = dict(base_draft.fields)
        updated_fields["lane_code"] = f"{origin_state}->{dest_state}"

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


class MercuryGateCarrierTransformerV1(TransformerPort):
    """Version 1 pure transformer for MercuryGate TMS carriers."""

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
    "MercuryGateCarrierTransformerV1",
    "MercuryGateLoadTransformerV1",
    "MercuryGateLoadTransformerV2",
]
