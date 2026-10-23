"""Pure functional L2/L3 transformer for Itron OpenWay Riva MDM streams."""

from __future__ import annotations

from seedwork.domain.types import JsonDict, JsonValue

from ip.application.domains.energy.canonical import EnergyEntityType
from ip.engine.ports.outbound.transformer_hook_port import (
    ExtractedReplicaDTO,
    NormalizedRecordDTO,
    TransformerHookPort,
)


class ItronMdmTransformer(TransformerHookPort):
    """Pure transformer converting Itron MDM raw payloads into L2 replicas and L3 canonical Energy records."""

    @property
    def app_id(self) -> str:
        return "itron_mdm"

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
            else str(payload.get("stream_name", "interval_reads"))
        )

        raw_items = payload.get("records")
        item: JsonDict
        if isinstance(raw_items, list) and raw_items and isinstance(raw_items[0], dict):
            item = raw_items[0]
        else:
            item = payload

        if stream_name == "interval_reads":
            meter_id = str(item.get("meter_id") or item.get("meter_serial") or "")
            ts = str(item.get("timestamp") or "")
            if not meter_id or not ts:
                return None
            ext_id = f"{meter_id}:{ts}"
        else:
            ext_id = str(item.get("id") or item.get("meter_id") or item.get("meter_serial") or "")
            if not ext_id:
                return None

        return ExtractedReplicaDTO(
            entity_type=stream_name,
            entity_id=ext_id,
            data=item,
        )

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
    def _safe_int(val: object, default: int = 15) -> int:
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

    def normalize(
        self,
        replica: ExtractedReplicaDTO,
    ) -> NormalizedRecordDTO | None:
        replica_payload = replica.data
        if replica.entity_type in ("interval_reads", "meters"):
            meter_serial = str(
                replica_payload.get("meter_serial")
                or replica_payload.get("serial_number")
                or replica_payload.get("meter_id")
                or replica_payload.get("id")
                or ""
            )
            if not meter_serial:
                return None

            raw_ts = replica_payload.get("timestamp") or replica_payload.get("last_reading_time")
            if not raw_ts:
                return None
            timestamp = str(raw_ts)

            kwh_delivered = self._safe_float(replica_payload.get("kwh_delivered"), 0.0)
            kwh_received = self._safe_float(replica_payload.get("kwh_received"), 0.0)
            interval_minutes = self._safe_int(replica_payload.get("interval_minutes"), 15)
            quality_flag = str(replica_payload.get("quality") or "VALIDATED")

            return NormalizedRecordDTO(
                canonical_type=EnergyEntityType.MDM_METER_READING,
                source_id=replica.entity_id,
                data={
                    "meter_serial_number": meter_serial,
                    "service_point_id": replica_payload.get("service_point_id"),
                    "reading_timestamp": timestamp,
                    "interval_minutes": interval_minutes,
                    "kwh_delivered": kwh_delivered,
                    "kwh_received": kwh_received,
                    "quality_flag": quality_flag,
                },
            )

        if replica.entity_type == "service_points":
            sp_id = str(replica_payload.get("id") or replica.entity_id)
            if not sp_id:
                return None
            return NormalizedRecordDTO(
                canonical_type=EnergyEntityType.MDM_SERVICE_POINT,
                source_id=sp_id,
                data={
                    "service_point_external_id": sp_id,
                    "meter_serial_number": replica_payload.get("meter_id"),
                    "customer_external_id": replica_payload.get("customer_id"),
                    "service_address": replica_payload.get("address"),
                    "status": str(replica_payload.get("status") or "ACTIVE"),
                },
            )

        return None
