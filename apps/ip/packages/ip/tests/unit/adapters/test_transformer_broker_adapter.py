"""Unit tests for TransformerRegistry and TransformerBrokerAdapter."""

from __future__ import annotations

from ip.engine.adapters.outbound.transformers.transformer_broker_adapter import (
    TransformerBrokerAdapter,
)
from ip.engine.adapters.outbound.transformers.transformer_registry import TransformerRegistry
from ip.engine.ports.outbound.transformer_hook_port import (
    NormalizedRecordDTO,
    ReplicaSnapshotDTO,
    TransformerHookPort,
)


class _SyntheticAlphaTransformer(TransformerHookPort):
    @property
    def app_id(self) -> str:
        return "acme_source"

    def normalize(self, replica: ReplicaSnapshotDTO) -> NormalizedRecordDTO | None:
        source_id = str(replica.data.get("external_id", replica.record_key))
        return NormalizedRecordDTO(
            canonical_type="canonical.record_alpha.v1",
            source_id=source_id,
            data={"external_id": source_id, "status": "ACTIVE"},
        )


def test_transformer_broker_routes_to_registered_transformers() -> None:
    registry = TransformerRegistry()
    registry.register("acme_source", _SyntheticAlphaTransformer())
    broker = TransformerBrokerAdapter(registry)

    replica = ReplicaSnapshotDTO(
        stream="records_alpha",
        record_key="rk_01",
        primary_key_values=("REC-9001", "2026-10-22T10:00:00Z"),
        data={
            "external_id": "REC-9001",
            "timestamp": "2026-10-22T10:00:00Z",
            "amount": 12.5,
        },
    )
    normalized = broker.normalize(app_id="acme_source", replica=replica)
    assert normalized is not None
    assert normalized.canonical_type == "canonical.record_alpha.v1"

    unknown_normalized = broker.normalize(app_id="unregistered_app", replica=replica)
    assert unknown_normalized is None
