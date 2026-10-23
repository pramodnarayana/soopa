"""Unit tests for TransformerRegistry and TransformerBrokerAdapter."""

from __future__ import annotations

from ip.application.domains.energy.canonical import EnergyEntityType
from ip.application.transformers.energy.itron_mdm import ItronMdmTransformer
from ip.application.transformers.tms.mercury_gate import MercuryGateTransformer
from ip.engine.adapters.outbound.transformers.transformer_broker_adapter import (
    TransformerBrokerAdapter,
)
from ip.engine.adapters.outbound.transformers.transformer_registry import TransformerRegistry
from ip.engine.ports.outbound.transformer_hook_port import ReplicaSnapshotDTO


def test_transformer_broker_routes_to_registered_transformers() -> None:
    registry = TransformerRegistry()
    registry.register("itron_mdm", ItronMdmTransformer())
    registry.register("mercury_gate", MercuryGateTransformer())
    broker = TransformerBrokerAdapter(registry)

    replica = ReplicaSnapshotDTO(
        stream="interval_reads",
        record_key="rk_01",
        primary_key_values=("MTR-9001", "2026-10-22T10:00:00Z"),
        data={
            "meter_id": "MTR-9001",
            "timestamp": "2026-10-22T10:00:00Z",
            "kwh_delivered": 12.5,
            "kwh_received": 0.4,
            "quality": "VALIDATED",
        },
    )
    normalized = broker.normalize(app_id="itron_mdm", replica=replica)
    assert normalized is not None
    assert normalized.canonical_type == EnergyEntityType.MDM_METER_READING

    unknown_normalized = broker.normalize(app_id="unregistered_app", replica=replica)
    assert unknown_normalized is None
