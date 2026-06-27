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
        for txn in parsed_payload.transactions:
            if txn.transaction_type == transaction_type:
                return txn.data
        return {}

    async def translate_json_to_edi(
        self, payload: dict[str, Any], standard: str, transaction_type: str
    ) -> bytes:
        """
        Translates JSON to EDI using the wrapped BOTS facade.
        """
        raise NotImplementedError("JSON to EDI translation is not yet supported via BOTS.")
