from typing import Any, Protocol

from pydantic import BaseModel


class TranslatedTransaction(BaseModel):
    transaction_type: str
    isa_sender_id: str | None = None
    isa_receiver_id: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    control_number: str | None = None
    payload: dict[str, Any]


class TransformerPort(Protocol):
    """
    Focused port for EDI/JSON payload translation.
    Used by the translation worker.
    """

    async def translate_edi_to_json(
        self, payload: bytes, standard: str, transaction_type: str
    ) -> list[TranslatedTransaction]:
        """Translates raw EDI bytes into a Canonical JSON Dictionary."""
        ...

    async def translate_json_to_edi(
        self,
        payload: dict[str, Any] | list[Any],
        standard: str,
        transaction_type: str,
        route_config: dict[str, Any],
    ) -> bytes:
        """Translates a Canonical JSON Dictionary into raw EDI bytes."""
        ...
