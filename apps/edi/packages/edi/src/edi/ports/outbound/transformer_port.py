from typing import Any, Protocol

from pydantic import BaseModel


class TransformedTransaction(BaseModel):
    transaction_type: str
    isa_sender_id: str | None = None
    isa_receiver_id: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    control_number: str | None = None
    payload: dict[str, Any]


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
        payload: dict[str, Any] | list[Any],
        standard: str,
        transaction_type: str,
        route_config: dict[str, Any],
    ) -> bytes:
        """Transforms a Canonical JSON Dictionary into raw EDI bytes."""
        ...
