"""Adapter executing pure TransformerHookPort implementations for replica extraction and canonical normalization."""

from __future__ import annotations

import structlog
from ip.engine.adapters.outbound.transformers.transformer_registry import TransformerRegistry
from ip.engine.ports.outbound.transformer_hook_port import (
    ExtractedReplicaDTO,
    NormalizedRecordDTO,
)
from seedwork.domain.types import JsonDict, JsonValue

logger = structlog.get_logger(__name__)


class TransformerBrokerAdapter:
    """Dispatches raw payloads and replica snapshots to registered pure TransformerHookPort implementations."""

    def __init__(self, registry: TransformerRegistry) -> None:
        self._registry = registry

    def extract_replica(
        self,
        app_id: str,
        payload: JsonValue,
        context: JsonDict | None = None,
    ) -> ExtractedReplicaDTO | None:
        stream_name = (
            str(context.get("stream_name")) if context and "stream_name" in context else None
        )
        transformer = self._registry.resolve(app_id, stream_name)
        if transformer is None:
            logger.info(
                "transformer_not_registered_skipping_extract",
                app_id=app_id,
                stream_name=stream_name,
            )
            return None
        return transformer.extract_replica(payload=payload, context=context)

    def normalize(
        self,
        app_id: str,
        replica: ExtractedReplicaDTO,
    ) -> NormalizedRecordDTO | None:
        transformer = self._registry.resolve(app_id, replica.entity_type)
        if transformer is None:
            logger.info(
                "transformer_not_registered_skipping_normalize",
                app_id=app_id,
                entity_type=replica.entity_type,
            )
            return None
        return transformer.normalize(replica=replica)
