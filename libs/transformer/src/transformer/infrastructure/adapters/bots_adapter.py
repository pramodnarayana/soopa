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

        # Validate payload before attempting to load backend
        if not raw_edi:
            raise TranslationError("Payload is completely empty, Bots engine aborted.")

        # Native BOTS Integration - import only after validation passes
        try:
            import bots  # type: ignore # Native import from our vendored workspace library!
        except ImportError as e:
            raise TranslationError(
                f"Bots EDI engine backend is not available or failed to load: {e}"
            ) from e

        logger.debug(f"Bots library loaded from: {bots.__file__}")

        # In a real implementation, we will pass the bytes directly to
        # bots.inmessage or bots.engine to bypass its filesystem overhead.

        # Fail fast: the Bots integration is not yet complete
        # Do not return fabricated data that would persist to the database
        raise TranslationError(
            "Bots EDI translation is not yet fully implemented. "
            "Refusing to return stub data that would corrupt the database."
        )
