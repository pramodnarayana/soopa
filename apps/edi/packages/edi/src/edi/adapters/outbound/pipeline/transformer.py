import asyncio
from typing import Any, cast

from edi.adapters.outbound.transformer.domain.envelope.edifact import (
    EdifactEnvelopeBuilder,
)
from edi.adapters.outbound.transformer.domain.envelope.x12 import X12EnvelopeBuilder
from edi.adapters.outbound.transformer.domain.exceptions import TransformationError
from edi.adapters.outbound.transformer.infrastructure.adapters.bots_adapter import BotsEDIAdapter
from edi.domain.types import AstNode
from edi.ports.outbound.transformer_port import TransformedTransaction, TransformerPort


class BotsTransformerAdapter(TransformerPort):
    """
    Concrete implementation of TransformerPort using the BotsEDIAdapter from the transformer lib.
    """

    def __init__(self) -> None:
        self._adapter = BotsEDIAdapter()

    async def transform_edi_to_json(
        self, payload: bytes, standard: str, transaction_type: str
    ) -> list[TransformedTransaction]:
        """
        Transforms EDI to JSON using the wrapped BOTS facade.
        """
        parsed_payload = await self._adapter.transform(payload)
        transactions = []
        for txn in parsed_payload.transactions:
            if (
                not transaction_type
                or transaction_type == "UNKNOWN"
                or txn.transaction_type == transaction_type
            ):
                transactions.append(
                    TransformedTransaction(
                        transaction_type=txn.transaction_type,
                        isa_sender_id=parsed_payload.sender_id,
                        isa_receiver_id=parsed_payload.receiver_id,
                        gs_sender_id=txn.gs_sender_id,
                        gs_receiver_id=txn.gs_receiver_id,
                        control_number=txn.control_number,
                        payload=cast("AstNode", txn.data),
                    )
                )
        return transactions

    async def transform_json_to_edi(
        self,
        payload: dict[str, Any] | list[Any],
        standard: str,
        transaction_type: str,
        route_config: dict[str, Any],
    ) -> bytes:
        """
        Transforms JSON to EDI using the wrapped BOTS facade.
        """

        if isinstance(payload, dict) and (
            "interchange_ISA" in payload or "interchange_UNB" in payload
        ):
            ast_dict: dict[str, Any] = payload
        else:
            if standard.lower() == "x12":
                ast_dict = X12EnvelopeBuilder.build(route_config, payload)
            elif standard.lower() == "edifact":
                ast_dict = EdifactEnvelopeBuilder.build(route_config, payload)
            else:
                raise TransformationError(
                    message=f"Unsupported standard for envelope building: {standard}"
                )

        edi_str, errors = await asyncio.to_thread(
            self._adapter.serialize_to_edi, ast_dict, standard=standard.lower()
        )

        fatal_errors = [e for e in errors if not e.startswith("[W")]
        if fatal_errors:
            raise TransformationError(message="\n".join(fatal_errors), errors=fatal_errors)

        return edi_str.encode("utf-8")
