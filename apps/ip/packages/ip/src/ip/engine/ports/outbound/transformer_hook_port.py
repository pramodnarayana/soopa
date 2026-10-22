"""Strict hexagonal boundary contract for pure functional data transformers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from seedwork.domain.types import JsonDict, JsonValue

from ip.engine.domain.enums import NormalizedEntityType


@dataclass(frozen=True)
class ExtractedReplicaDTO:
    """Stable entity identity and attributes extracted from a raw vendor payload (Layer 2)."""

    entity_type: str
    entity_id: str
    data: JsonDict


@dataclass(frozen=True)
class NormalizedRecordDTO:
    """Canonical domain record produced by Layer 3 normalization."""

    canonical_type: NormalizedEntityType
    source_id: str
    data: JsonDict


class TransformerHookPort(Protocol):
    """The strict boundary contract every application transformer must satisfy.

    Invariants:
    1. Zero database handles.
    2. Zero network I/O.
    3. Pure deterministic functions: f(in) -> out.
    """

    @property
    def app_id(self) -> str:
        """Identifier of the application/vendor handled by this transformer."""
        ...

    def extract_replica(
        self,
        payload: JsonValue,
        context: JsonDict | None = None,
    ) -> ExtractedReplicaDTO | None:
        """L2 Extraction Hook. Extracts entity_type, entity_id, and unmutated attribute dict."""
        ...

    def normalize(
        self,
        replica: ExtractedReplicaDTO,
    ) -> NormalizedRecordDTO | None:
        """L3 Normalization Hook. Maps a replica snapshot to a Canonical Domain DTO."""
        ...
