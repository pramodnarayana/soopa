import logging

import bots_core.infrastructure.config.botsinit as botsinit
from sqlalchemy.orm import Session

from transformer.application.ports import EDITranslatorPort
from transformer.domain.exceptions import TranslationError
from transformer.domain.models import ParsedEdiPayload
from transformer.infrastructure.adapters.bots_db_adapter import SqlAlchemyBotsDatabaseAdapter

logger = logging.getLogger(__name__)


_bots_initialized = False


class BotsEDIAdapter(EDITranslatorPort):
    """
    Adapter to run the vendored BOTS EDI translation engine natively in-memory.
    No sub-processes, no external cron jobs.
    """

    def __init__(self, config_dir: str, session: Session):
        self.config_dir = config_dir
        self.session = session
        self._ensure_global_bootstrap()

    def _ensure_global_bootstrap(self) -> None:
        """Bootstraps the process-global BOTS environment exactly once."""
        global _bots_initialized
        if not _bots_initialized:
            logger.info(f"Initializing global BOTS environment with config_dir={self.config_dir}")
            botsinit.generalinit(self.config_dir)
            botsinit.initenginelogging("bots.engine")
            _bots_initialized = True

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
            import bots_core  # type: ignore # Native import from our vendored workspace library!
            from bots_core.infrastructure.config.context import (
                BotsContext,
                reset_context,
                set_context,
            )
        except ImportError as e:
            raise TranslationError(
                f"Bots EDI engine backend is not available or failed to load: {e}"
            ) from e

        logger.debug(f"Bots library loaded from: {bots_core.__file__}")

        # Setup strict request isolation
        ctx = BotsContext()
        ctx.db_port = SqlAlchemyBotsDatabaseAdapter(self.session)
        token = set_context(ctx)

        try:
            # In a real implementation, we will pass the bytes directly to
            # bots.inmessage or bots.engine to bypass its filesystem overhead.

            # Fail fast: the Bots integration is not yet complete
            # Do not return fabricated data that would persist to the database
            raise TranslationError(
                "Bots EDI translation is not yet fully implemented. "
                "Refusing to return stub data that would corrupt the database."
            )
        finally:
            reset_context(token)
