"""Pure functional Layer 3 normalizer for MercuryGate TMS streams."""

from __future__ import annotations

from decimal import Decimal

from ip.application.domains.tms.canonical import TmsEntityType
from ip.engine.ports.outbound.transformer_hook_port import (
    NormalizedRecordDTO,
    ReplicaSnapshotDTO,
    TransformerHookPort,
)


class MercuryGateTransformer(TransformerHookPort):
    """Pure normalizer converting MercuryGate TMS L2 replica snapshots into L3 canonical TMS records."""

    @property
    def app_id(self) -> str:
        return "mercury_gate"

    @staticmethod
    def _safe_float(val: object, default: float = 0.0) -> float:
        if val is None:
            return default
        if isinstance(val, (int, float)):
            return float(val)
        try:
            return float(str(val))
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _safe_decimal(val: object, default: Decimal = Decimal("0.00")) -> Decimal:
        if val is None:
            return default
        try:
            return Decimal(str(val))
        except (ValueError, TypeError, ArithmeticError):
            return default

    def normalize(
        self,
        replica: ReplicaSnapshotDTO,
    ) -> NormalizedRecordDTO | None:
        replica_payload = replica.data
        if replica.stream == "loads":
            load_ref = str(
                replica_payload.get("load_id")
                or replica_payload.get("reference_number")
                or replica_payload.get("id")
                or (replica.primary_key_values[0] if replica.primary_key_values else "")
                or replica.record_key
            )
            if not load_ref:
                return None

            weight_lbs = self._safe_float(replica_payload.get("total_weight_lbs"), 0.0)
            charge_usd = self._safe_decimal(
                replica_payload.get("freight_charge_usd"), Decimal("0.00")
            )

            origin_city = str(replica_payload.get("origin_city") or "UNKNOWN")
            origin_state = str(replica_payload.get("origin_state") or "NA")
            destination_city = str(replica_payload.get("destination_city") or "UNKNOWN")
            destination_state = str(replica_payload.get("destination_state") or "NA")
            status = str(replica_payload.get("status") or "TENDERED")

            return NormalizedRecordDTO(
                canonical_type=TmsEntityType.TMS_LOAD,
                source_id=load_ref,
                data={
                    "load_reference_number": load_ref,
                    "carrier_scac": replica_payload.get("carrier_scac"),
                    "origin_city": origin_city,
                    "origin_state": origin_state,
                    "destination_city": destination_city,
                    "destination_state": destination_state,
                    "status": status,
                    "total_weight_lbs": weight_lbs,
                    "freight_charge_usd": charge_usd,
                },
            )

        if replica.stream == "carriers":
            scac = str(
                replica_payload.get("scac")
                or replica_payload.get("scac_code")
                or (replica.primary_key_values[0] if replica.primary_key_values else "")
                or replica.record_key
            )
            if not scac:
                return None
            carrier_name = str(replica_payload.get("carrier_name") or scac)
            status = str(replica_payload.get("status") or "ACTIVE")

            return NormalizedRecordDTO(
                canonical_type=TmsEntityType.TMS_CARRIER,
                source_id=scac,
                data={
                    "scac_code": scac,
                    "carrier_name": carrier_name,
                    "dot_number": replica_payload.get("dot_number"),
                    "mc_number": replica_payload.get("mc_number"),
                    "status": status,
                },
            )

        return None
