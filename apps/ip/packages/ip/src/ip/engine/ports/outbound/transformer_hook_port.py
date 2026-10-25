"""Strict hexagonal boundary contract for pure functional Layer 3 data normalizers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from seedwork.domain.types import JsonDict, JsonPrimitive

from ip.engine.domain.models.normalized_record import CanonicalDataDict


@dataclass(frozen=True)
class ReplicaSnapshotDTO:
    """Immutable Layer 2 replica snapshot input passed to Layer 3 normalizers."""

    stream: str
    record_key: str
    data: JsonDict
    primary_key_values: tuple[JsonPrimitive, ...] = ()


@dataclass(frozen=True)
class NormalizedRecordDTO:
    """Canonical domain record produced by Layer 3 normalization."""

    canonical_type: str
    source_id: str
    data: CanonicalDataDict


class TransformerHookPort(Protocol):
    """The strict boundary contract every application L3 normalizer must satisfy.

    Invariants:
    1. Zero database handles.
    2. Zero network I/O.
    3. Pure deterministic functions: f(in) -> out.
    """

    @property
    def app_id(self) -> str:
        """Identifier of the application/vendor handled by this transformer."""
        ...

    def normalize(
        self,
        replica: ReplicaSnapshotDTO,
    ) -> NormalizedRecordDTO | None:
        """L3 Normalization Hook. Maps an L2 replica snapshot to a Canonical Domain DTO."""
        ...
