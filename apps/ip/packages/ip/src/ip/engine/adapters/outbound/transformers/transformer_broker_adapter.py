"""Adapter executing pure TransformerHookPort implementations for Layer 3 canonical normalization."""

from __future__ import annotations

import structlog
from ip.engine.adapters.outbound.transformers.transformer_registry import TransformerRegistry
from ip.engine.ports.outbound.transformer_hook_port import (
    NormalizedRecordDTO,
    ReplicaSnapshotDTO,
)

logger = structlog.get_logger(__name__)


class TransformerBrokerAdapter:
    """Dispatches Layer 2 replica snapshots to registered pure TransformerHookPort implementations."""

    def __init__(self, registry: TransformerRegistry) -> None:
        self._registry = registry

    def normalize(
        self,
        app_id: str,
        replica: ReplicaSnapshotDTO,
    ) -> NormalizedRecordDTO | None:
        transformer = self._registry.resolve(app_id, replica.stream)
        if transformer is None:
            logger.info(
                "transformer_not_registered_skipping_normalize",
                app_id=app_id,
                stream=replica.stream,
            )
            return None
        return transformer.normalize(replica=replica)
