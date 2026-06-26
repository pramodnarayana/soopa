import logging

import bots_core.infrastructure.config.botsglobal as botsglobal
import bots_core.infrastructure.config.botsinit as botsinit
from sqlalchemy.orm import Session

from transformer.application.ports import EDITranslatorPort
from transformer.domain.exceptions import TranslationError
from transformer.domain.models import ParsedEdiPayload
from transformer.infrastructure.adapters.bots_db_adapter import SqlAlchemyBotsDatabaseAdapter

logger = logging.getLogger(__name__)


class BotsEDIAdapter(EDITranslatorPort):
    """
    Adapter to run the vendored BOTS EDI translation engine natively in-memory.
    No sub-processes, no external cron jobs.
    """

    def __init__(self, config_dir: str, session: Session):
        self.config_dir = config_dir
        self.session = session
        self._initialize_engine()

    def _initialize_engine(self) -> None:
        """Bootstraps the BOTS engine environment."""
        logger.info(f"Initializing BOTS engine with config_dir={self.config_dir}")
        botsinit.generalinit(self.config_dir)
        botsinit.initenginelogging("bots.engine")

        # Inject the SQLAlchemy DB adapter into the BOTS core
        botsglobal.db_port = SqlAlchemyBotsDatabaseAdapter(self.session)

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
        except ImportError as e:
            raise TranslationError(
                f"Bots EDI engine backend is not available or failed to load: {e}"
            ) from e

        logger.debug(f"Bots library loaded from: {bots_core.__file__}")

        # In a real implementation, we will pass the bytes directly to
        # bots.inmessage or bots.engine to bypass its filesystem overhead.

        # Fail fast: the Bots integration is not yet complete
        # Do not return fabricated data that would persist to the database
        raise TranslationError(
            "Bots EDI translation is not yet fully implemented. "
            "Refusing to return stub data that would corrupt the database."
        )
