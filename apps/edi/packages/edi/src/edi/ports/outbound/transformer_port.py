from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from seedwork.domain.types import JsonValue

from edi.domain.types import AstNode


@dataclass(frozen=True)
class TransformedTransaction:
    transaction_type: str
    payload: AstNode
    isa_sender_id: str | None = None
    isa_receiver_id: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    control_number: str | None = None


class TransformerPort(Protocol):
    """
    Focused port for EDI/JSON payload transformation.
    Used by the transformation worker.
    """

    async def transform_edi_to_json(
        self, payload: bytes, standard: str, transaction_type: str
    ) -> list[TransformedTransaction]:
        """Transforms raw EDI bytes into a Canonical JSON Dictionary."""
        ...

    async def transform_json_to_edi(
        self,
        payload: AstNode | list[AstNode],
        standard: str,
        transaction_type: str,
        route_config: dict[str, JsonValue],
    ) -> bytes:
        """Transforms a Canonical JSON Dictionary into raw EDI bytes."""
        ...
