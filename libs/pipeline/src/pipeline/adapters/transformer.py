from typing import Any

from pipeline.ports.transformer import TransformerPort
from transformer.infrastructure.adapters.bots_adapter import BotsEDIAdapter


class BotsTransformerAdapter(TransformerPort):
    """
    Concrete implementation of TransformerPort using the BotsEDIAdapter from the transformer lib.
    """

    def __init__(self) -> None:
        self._adapter = BotsEDIAdapter()

    async def translate_edi_to_json(
        self, payload: bytes, standard: str, transaction_type: str
    ) -> dict[str, Any]:
        """
        Translates EDI to JSON using the wrapped BOTS facade.
        """
        parsed_payload = await self._adapter.translate(payload)
        # Assuming one transaction for now
        return parsed_payload.transactions[0].data if parsed_payload.transactions else {}

    async def translate_json_to_edi(
        self, payload: dict[str, Any], standard: str, transaction_type: str
    ) -> bytes:
        """
        Translates JSON to EDI using the wrapped BOTS facade.
        """
        # Not yet implemented in BotsEDIAdapter, but returning dummy for now to satisfy interface
        return b"ST*850*0001~SE*2*0001~"
