"""L3 Normalization Domain Protocols and Abstract Interfaces."""

from __future__ import annotations

from typing import Protocol

from seedwork.domain.types import JsonDict

from ip.engine.domain.normalization.dtos import (
    ReplicaSnapshot,
    TransformationContext,
    TransformationResult,
)
from ip.engine.domain.normalization.enums import RuleSeverity


class QualityRule(Protocol):
    """Protocol for pure business and data quality validation rules."""

    @property
    def code(self) -> str: ...

    @property
    def severity(self) -> RuleSeverity: ...

    def evaluate(self, fields: JsonDict) -> str | None: ...


class DomainTransformerProtocol(Protocol):
    """Pure domain protocol for deterministic Layer 3 normalization transformers."""

    @property
    def transformation_id(self) -> str: ...

    @property
    def transformation_version(self) -> int: ...

    @property
    def target_types(self) -> tuple[str, ...]: ...

    def transform(
        self, replica: ReplicaSnapshot, context: TransformationContext
    ) -> TransformationResult: ...


__all__ = [
    "DomainTransformerProtocol",
    "QualityRule",
]
