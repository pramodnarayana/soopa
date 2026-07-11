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
        self,
        payload: dict[str, Any] | list[dict[str, Any]],
        standard: str,
        transaction_type: str,
        route_config: dict[str, Any],
    ) -> bytes:
        """
        Translates JSON to EDI using the wrapped BOTS facade.
        """
        import asyncio

        from transformer.domain.exceptions import TranslationError

        if isinstance(payload, dict) and (
            "interchange_ISA" in payload or "interchange_UNB" in payload
        ):
            ast_dict: dict[str, Any] = payload
        else:
            if standard.lower() == "x12":
                from transformer.domain.envelope.x12 import X12EnvelopeBuilder

                ast_dict = X12EnvelopeBuilder.build(route_config, payload)
            elif standard.lower() == "edifact":
                from transformer.domain.envelope.edifact import EdifactEnvelopeBuilder

                ast_dict = EdifactEnvelopeBuilder.build(route_config, payload)
            else:
                raise TranslationError(
                    message=f"Unsupported standard for envelope building: {standard}"
                )

        edi_str, errors = await asyncio.to_thread(
            self._adapter.serialize_to_edi, ast_dict, standard=standard.lower()
        )

        fatal_errors = [e for e in errors if not e.startswith("[W")]
        if fatal_errors:
            raise TranslationError(message="\n".join(fatal_errors), errors=fatal_errors)

        return edi_str.encode("utf-8")
