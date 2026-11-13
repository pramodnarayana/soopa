"""Pure L3 canonical transformers for AMI service points (`energy.ami_service_point`)."""

from __future__ import annotations

from ip.engine.domain.normalization.enums import NormalizationRejectionReason
from ip.engine.domain.normalization.transformation import (
    CanonicalDraft,
    ReplicaSnapshot,
    TransformationContext,
    TransformationRejection,
    TransformationResult,
)
from ip.engine.ports.outbound.transformer_port import TransformerPort
from ip.solutions.domains.energy.canonical import (
    EnergyEntityType,
    ServicePointStatus,
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
        sp_id = str(payload.get("service_point_id") or replica.record_key or "").strip()
        if not sp_id:
            return TransformationResult(
                rejections=(
                    TransformationRejection(
                        reason=NormalizationRejectionReason.MISSING_REQUIRED_FIELD,
                        field_path="service_point_id",
                        detail="Missing required service point identifier.",
                    ),
                )
            )

        meter_serial_raw = payload.get("meter_serial") or payload.get("meter_id")
        meter_serial = (
            str(meter_serial_raw).strip()
            if meter_serial_raw is not None and str(meter_serial_raw).strip()
            else None
        )
        customer_id_raw = payload.get("customer_id")
        customer_id = (
            str(customer_id_raw).strip()
            if customer_id_raw is not None and str(customer_id_raw).strip()
            else None
        )
        address_raw = payload.get("service_address") or payload.get("address")
        address = (
            str(address_raw).strip()
            if address_raw is not None and str(address_raw).strip()
            else None
        )
        grid_region_raw = payload.get("grid_region")
        grid_region = (
            str(grid_region_raw).strip()
            if grid_region_raw is not None and str(grid_region_raw).strip()
            else None
        )

        return TransformationResult(
            drafts=(
                CanonicalDraft(
                    canonical_type=EnergyEntityType.MDM_SERVICE_POINT.value,
                    source_id=sp_id,
                    fields={
                        "service_point_external_id": sp_id,
                        "meter_serial_number": meter_serial,
                        "customer_external_id": customer_id,
                        "service_address": address,
                        "grid_region": grid_region,
                        "status": str(payload.get("status") or ServicePointStatus.ACTIVE.value),
                    },
                ),
            )
        )
