"""Unit tests for ItronMdmTransformer (pure Layer 3 Energy MDM data normalizer)."""

from __future__ import annotations

from ip.application.domains.energy.canonical import EnergyEntityType
from ip.application.transformers.energy.itron_mdm import ItronMdmTransformer
from ip.engine.ports.outbound.transformer_hook_port import ReplicaSnapshotDTO


def test_itron_mdm_transformer_normalizes_interval_reads() -> None:
    transformer = ItronMdmTransformer()
    assert transformer.app_id == "itron_mdm"

    replica = ReplicaSnapshotDTO(
        stream="interval_reads",
        record_key="rk_9001",
        primary_key_values=("MTR-9001", "2026-10-22T10:00:00Z"),
        data={
            "meter_id": "MTR-9001",
            "timestamp": "2026-10-22T10:00:00Z",
            "kwh_delivered": 12.5,
            "kwh_received": 0.4,
            "quality": "VALIDATED",
        },
    )

    normalized = transformer.normalize(replica)
    assert normalized is not None
    assert normalized.canonical_type == EnergyEntityType.MDM_METER_READING
    assert normalized.source_id == "MTR-9001:2026-10-22T10:00:00Z"
    assert normalized.data["kwh_delivered"] == 12.5


def test_itron_mdm_transformer_normalizes_service_points() -> None:
    transformer = ItronMdmTransformer()
    replica = ReplicaSnapshotDTO(
        stream="service_points",
        record_key="rk_sp_500",
        primary_key_values=("SP-500",),
        data={
            "id": "SP-500",
            "meter_id": "MTR-500",
            "customer_id": "CUST-500",
            "address": "500 Grid Ave",
            "status": "ACTIVE",
        },
    )

    normalized = transformer.normalize(replica)
    assert normalized is not None
    assert normalized.canonical_type == EnergyEntityType.MDM_SERVICE_POINT
    assert normalized.source_id == "SP-500"
    assert normalized.data["service_address"] == "500 Grid Ave"


def test_itron_mdm_transformer_handles_invalid_or_incomplete_payloads() -> None:
    transformer = ItronMdmTransformer()

    empty_meter_replica = ReplicaSnapshotDTO(
        stream="interval_reads",
        record_key="MTR-1:ts",
        data={},
    )
    assert transformer.normalize(empty_meter_replica) is None

    empty_sp_replica = ReplicaSnapshotDTO(
        stream="service_points",
        record_key="",
        data={},
    )
    assert transformer.normalize(empty_sp_replica) is None

    unknown_replica = ReplicaSnapshotDTO(
        stream="unknown_stream",
        record_key="u_1",
        data={"id": "u_1"},
    )
    assert transformer.normalize(unknown_replica) is None
