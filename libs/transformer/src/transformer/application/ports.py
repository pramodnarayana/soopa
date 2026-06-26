from typing import Protocol

from transformer.domain.models import ParsedEdiPayload


class EDITranslatorPort(Protocol):
    """
    Inbound port for translating raw EDI payloads into standardized JSON.
    This encapsulates the BOTS translation engine or any future EDI engine.
    """

    async def translate(self, raw_edi: bytes) -> ParsedEdiPayload:
        """
        Translates raw X12/EDIFACT bytes into a ParsedEdiPayload domain model.

        Raises:
            TranslationError: If the EDI engine fails to parse the structure.
            ComplianceError: If the document violates business compliance rules.
        """
        ...
