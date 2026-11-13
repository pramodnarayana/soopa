"""Pure L3 canonical transformers for Itron Premise / Service Point master records (`energy.itron_service_point`)."""

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


class ItronServicePointTransformerV1(TransformerPort):
    """Dedicated pure transformer for Itron Premise / Service Point master records."""

    @property
    def transformation_id(self) -> str:
        return "energy.itron_service_point"

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
        premise_id = str(payload.get("premise_id") or "").strip()
        if not premise_id:
            return TransformationResult(
                rejections=(
                    TransformationRejection(
                        reason=NormalizationRejectionReason.MISSING_REQUIRED_FIELD,
                        field_path="premise_id",
                        detail="Missing required Itron premise_id.",
                    ),
                )
            )

        serial_number = payload.get("serial_number")
        customer_ref = payload.get("customer_ref")
        address = payload.get("address")
        grid_zone = payload.get("grid_zone")

        return TransformationResult(
            drafts=(
                CanonicalDraft(
                    canonical_type=EnergyEntityType.MDM_SERVICE_POINT.value,
                    source_id=premise_id,
                    fields={
                        "service_point_external_id": premise_id,
                        "meter_serial_number": str(serial_number).strip()
                        if serial_number
                        else None,
                        "customer_external_id": str(customer_ref).strip() if customer_ref else None,
                        "service_address": str(address).strip() if address else None,
                        "grid_region": str(grid_zone).strip() if grid_zone else None,
                        "status": str(payload.get("status") or ServicePointStatus.ACTIVE.value),
                    },
                ),
            )
        )
