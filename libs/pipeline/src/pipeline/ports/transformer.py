from typing import Any, Protocol


class TransformerPort(Protocol):
    """
    Interface for the EDI translation engine.
    """

    async def translate_edi_to_json(
        self, payload: bytes, standard: str, transaction_type: str
    ) -> dict[str, Any]:
        """Translates raw EDI bytes into a Canonical JSON Dictionary."""
        ...

    async def translate_json_to_edi(
        self,
        payload: dict[str, Any],
        standard: str,
        transaction_type: str,
        route_config: dict[str, Any],
    ) -> bytes:
        """Translates a Canonical JSON Dictionary into raw EDI bytes."""
        ...
