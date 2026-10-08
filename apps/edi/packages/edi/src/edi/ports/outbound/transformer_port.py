from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from edi.domain.models.headers import EdiEnvelopeHeaders
from edi.domain.types import AstNode


@dataclass(frozen=True)
class ParsedEdiMessage:
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
    ) -> list[ParsedEdiMessage]:
        """Transforms raw EDI bytes into a Canonical JSON Dictionary."""
        ...

    async def transform_json_to_edi(
        self,
        payload: AstNode | list[AstNode],
        standard: str,
        transaction_type: str,
        edi_headers: EdiEnvelopeHeaders,
    ) -> bytes:
        """Transforms a Canonical JSON Dictionary into raw EDI bytes."""
        ...
