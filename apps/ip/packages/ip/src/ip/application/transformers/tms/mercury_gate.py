"""Pure functional L2/L3 transformer for MercuryGate TMS streams."""

from __future__ import annotations

from seedwork.domain.types import JsonDict, JsonValue

from ip.engine.domain.enums import NormalizedEntityType
from ip.engine.ports.outbound.transformer_hook_port import (
    ExtractedReplicaDTO,
    NormalizedRecordDTO,
    TransformerHookPort,
)


class MercuryGateTransformer(TransformerHookPort):
    """Pure transformer converting MercuryGate TMS payloads into L2 replicas and L3 canonical TMS records."""

    @property
    def app_id(self) -> str:
        return "mercury_gate"

    def extract_replica(
        self,
        payload: JsonValue,
        context: JsonDict | None = None,
    ) -> ExtractedReplicaDTO | None:
        if not isinstance(payload, dict):
            return None

        stream_name = (
            str(context["stream_name"])
            if context and "stream_name" in context
            else str(payload.get("stream_name", "loads"))
        )

        raw_items = payload.get("loads") or payload.get("carriers") or payload.get("records")
        item: JsonDict
        if isinstance(raw_items, list) and raw_items and isinstance(raw_items[0], dict):
            item = raw_items[0]
        else:
            item = payload

        ext_id = str(
            item.get("load_id")
            or item.get("reference_number")
            or item.get("scac")
            or item.get("id")
            or ""
        )
        if not ext_id:
            return None

        return ExtractedReplicaDTO(
            entity_type=stream_name,
            entity_id=ext_id,
            data=item,
        )

    def normalize(
        self,
        replica: ExtractedReplicaDTO,
    ) -> NormalizedRecordDTO | None:
        replica_payload = replica.data
        if replica.entity_type == "loads":
            load_ref = str(
                replica_payload.get("reference_number")
                or replica_payload.get("load_id")
                or replica_payload.get("id")
                or replica.entity_id
            )
            if not load_ref:
                return None

            raw_weight = replica_payload.get("total_weight_lbs", 0.0)
            weight_lbs = float(raw_weight) if isinstance(raw_weight, (int, float, str)) else 0.0
            raw_charge = replica_payload.get("freight_charge_usd", 0.0)
            charge_usd = float(raw_charge) if isinstance(raw_charge, (int, float, str)) else 0.0

            return NormalizedRecordDTO(
                canonical_type=NormalizedEntityType.TMS_LOAD,
                source_id=load_ref,
                data={
                    "load_reference_number": load_ref,
                    "carrier_scac": replica_payload.get("carrier_scac"),
                    "origin_city": str(replica_payload.get("origin_city", "UNKNOWN")),
                    "origin_state": str(replica_payload.get("origin_state", "NA")),
                    "destination_city": str(replica_payload.get("destination_city", "UNKNOWN")),
                    "destination_state": str(replica_payload.get("destination_state", "NA")),
                    "status": str(replica_payload.get("status", "TENDERED")),
                    "total_weight_lbs": weight_lbs,
                    "freight_charge_usd": charge_usd,
                },
            )

        if replica.entity_type == "carriers":
            scac = str(
                replica_payload.get("scac") or replica_payload.get("scac_code") or replica.entity_id
            )
            if not scac:
                return None
            return NormalizedRecordDTO(
                canonical_type=NormalizedEntityType.TMS_CARRIER,
                source_id=scac,
                data={
                    "scac_code": scac,
                    "carrier_name": str(replica_payload.get("carrier_name") or scac),
                    "dot_number": replica_payload.get("dot_number"),
                    "mc_number": replica_payload.get("mc_number"),
                    "status": str(replica_payload.get("status", "ACTIVE")),
                },
            )

        return None
