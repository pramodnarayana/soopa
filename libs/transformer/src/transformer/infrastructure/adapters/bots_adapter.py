import logging

from transformer.application.ports import EDITranslatorPort
from transformer.domain.exceptions import TranslationError
from transformer.domain.models import ParsedEdiPayload

logger = logging.getLogger(__name__)


class BotsEDIAdapter(EDITranslatorPort):
    """
    Infrastructure Adapter wrapping the vendored open-source Bots EDI Translator.
    Since Bots is now natively integrated in our monorepo, we import it directly
    and invoke it within the same process.
    """

    def __init__(self, bots_executable_path: str = "bots-engine"):
        self.bots_executable_path = bots_executable_path

    async def translate(self, raw_edi: bytes) -> ParsedEdiPayload:
        """
        Executes the Bots translation process.

        This translates raw X12/EDIFACT bytes into our pristine domain model.
        """
        logger.info(f"Invoking Bots EDI adapter with {len(raw_edi)} bytes of payload")

        # Native BOTS Integration:
        import bots  # type: ignore # Native import from our vendored workspace library!

        logger.debug(f"Bots library loaded from: {bots.__file__}")

        # In a real implementation, we will pass the bytes directly to
        # bots.inmessage or bots.engine to bypass its filesystem overhead.

        # Simulating an infrastructure failure if the payload is empty
        if not raw_edi:
            raise TranslationError("Payload is completely empty, Bots engine aborted.")

        # To support our 'Red-Green-Refactor' cycle without actually having
        # the legacy Bots library installed in this Python 3.11 environment,
        # we return a structurally compliant stub payload for now.
        return ParsedEdiPayload(
            sender_id="BOTS-ADAPTER-STUB",
            receiver_id="NEXIOM",
            interchange_control_number="0001",
            transactions=[],
        )
