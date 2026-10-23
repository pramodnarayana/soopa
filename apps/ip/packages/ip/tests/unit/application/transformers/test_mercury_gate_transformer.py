"""Unit tests for MercuryGateTransformer (pure Layer 3 TMS data normalizer)."""

from __future__ import annotations

from ip.application.domains.tms.canonical import TmsEntityType
from ip.application.transformers.tms.mercury_gate import MercuryGateTransformer
from ip.engine.ports.outbound.transformer_hook_port import ReplicaSnapshotDTO


def test_mercury_gate_transformer_normalizes_loads() -> None:
    transformer = MercuryGateTransformer()
    assert transformer.app_id == "mercury_gate"

    replica = ReplicaSnapshotDTO(
        stream="loads",
        record_key="rk_ld_7788",
        primary_key_values=("LD-2026-7788",),
        data={
            "reference_number": "LD-2026-7788",
            "carrier_scac": "ODFL",
            "origin_city": "Chicago",
            "origin_state": "IL",
            "destination_city": "Dallas",
            "destination_state": "TX",
            "status": "IN_TRANSIT",
            "total_weight_lbs": 42000.0,
            "freight_charge_usd": 3150.0,
        },
    )

    normalized = transformer.normalize(replica)
    assert normalized is not None
    assert normalized.canonical_type == TmsEntityType.TMS_LOAD
    assert normalized.source_id == "LD-2026-7788"
    assert normalized.data["carrier_scac"] == "ODFL"


def test_mercury_gate_transformer_normalizes_carriers() -> None:
    transformer = MercuryGateTransformer()
    replica = ReplicaSnapshotDTO(
        stream="carriers",
        record_key="rk_swft",
        primary_key_values=("SWFT",),
        data={
            "scac": "SWFT",
            "carrier_name": "Swift Transportation",
            "dot_number": "DOT-101",
            "mc_number": "MC-202",
            "status": "ACTIVE",
        },
    )

    normalized = transformer.normalize(replica)
    assert normalized is not None
    assert normalized.canonical_type == TmsEntityType.TMS_CARRIER
    assert normalized.source_id == "SWFT"
    assert normalized.data["carrier_name"] == "Swift Transportation"


def test_mercury_gate_transformer_handles_invalid_or_incomplete_payloads() -> None:
    transformer = MercuryGateTransformer()

    empty_load_replica = ReplicaSnapshotDTO(
        stream="loads",
        record_key="",
        data={},
    )
    assert transformer.normalize(empty_load_replica) is None

    empty_carrier_replica = ReplicaSnapshotDTO(
        stream="carriers",
        record_key="",
        data={},
    )
    assert transformer.normalize(empty_carrier_replica) is None

    unknown_replica = ReplicaSnapshotDTO(
        stream="unknown_stream",
        record_key="u_1",
        data={"id": "u_1"},
    )
    assert transformer.normalize(unknown_replica) is None
