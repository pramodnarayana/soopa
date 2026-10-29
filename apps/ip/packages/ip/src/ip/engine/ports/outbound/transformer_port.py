"""TransformerPort and TransformerRegistryPort for pure L3 normalization transformers."""

from __future__ import annotations

from typing import Protocol

from ip.engine.domain.normalization import (
    ReplicaSnapshot,
    TransformationContext,
    TransformationResult,
)


class TransformerPort(Protocol):
    """The strict boundary contract every L2 -> L3 Canonical Transformer must satisfy."""

    @property
    def transformation_id(self) -> str:
        """Unique business identifier of the transformer (e.g. 'energy.ami_meter_reading')."""
        ...

    @property
    def transformation_version(self) -> int:
        """Integer version of the transformer contract, bumped on behavioral change."""
        ...

    @property
    def target_types(self) -> tuple[str, ...]:
        """Canonical domain entity types produced by this transformer."""
        ...

    def transform(
        self, replica: ReplicaSnapshot, context: TransformationContext
    ) -> TransformationResult:
        """Pure transformation function converting an L2 replica into canonical drafts and rejections."""
        ...


class TransformerRegistryPort(Protocol):
    """Registry maintaining active and candidate pure code transformers."""

    def register(self, transformer: TransformerPort) -> None:
        """Register a transformer instance by its (transformation_id, transformation_version)."""
        ...

    def get(self, transformation_id: str, transformation_version: int) -> TransformerPort | None:
        """Retrieve a registered transformer for a specific version."""
        ...

    def get_latest(self, transformation_id: str) -> TransformerPort | None:
        """Retrieve the latest registered version of a transformer."""
        ...

    def list_transformers(self) -> tuple[TransformerPort, ...]:
        """List all currently registered transformers."""
        ...
