from typing import Protocol

from edi.adapters.outbound.transformer.domain.models import JsonDict, ParsedEdiPayload
from edi.domain.constants import EdiStandard


class EDITransformerPort(Protocol):
    """
    Inbound port for translating raw EDI payloads into standardized JSON.
    This encapsulates the BOTS translation engine or any future EDI engine.
    """

    async def transform(self, raw_edi: bytes) -> ParsedEdiPayload:
        """
        Transforms raw X12/EDIFACT bytes into a ParsedEdiPayload domain model.

        Raises:
            TransformationError: If the EDI engine fails to parse the structure.
            ComplianceError: If the document violates business compliance rules.
        """
        ...

    def get_raw_ast(self, raw_edi: bytes) -> tuple[JsonDict, list[str]]:
        """
        Returns the raw AST dictionary and any validation errors without creating a domain model.
        """
        ...

    def serialize_to_edi(
        self, ast_dict: JsonDict, standard: str = EdiStandard.X12
    ) -> tuple[str, list[str]]:
        """
        Serializes a JSON AST back into raw EDI format.

        Returns:
            A tuple of (generated_edi_string, list_of_errors).
        """
        ...
