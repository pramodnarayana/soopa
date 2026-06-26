import json
import logging
import os
import tempfile

from bots_core.facade import edi_to_json

from transformer.application.ports import EDITranslatorPort
from transformer.domain.exceptions import TranslationError
from transformer.domain.models import ParsedEdiPayload, TransactionSet

logger = logging.getLogger(__name__)


class BotsEDIAdapter(EDITranslatorPort):
    """
    Adapter to run the vendored BOTS EDI translation engine natively in-memory.
    No sub-processes, no external cron jobs.
    """

    def __init__(self) -> None:
        pass

    async def translate(self, raw_edi: bytes) -> ParsedEdiPayload:
        """
        Executes the Bots translation process.

        This translates raw X12/EDIFACT bytes into our pristine domain model.
        """
        logger.info(f"Invoking stateless Bots adapter with {len(raw_edi)} bytes of payload")

        # Validate payload before attempting to load backend
        if not raw_edi:
            raise TranslationError("Payload is completely empty, Bots engine aborted.")

        # We assume X12 for now. Extract actual messagetype from ST segment if possible.
        messagetype = "x12"
        try:
            raw_text = raw_edi.decode("utf-8", errors="ignore")
            if "ST*" in raw_text:
                # Naive extract: 'ST*850*...'
                messagetype = raw_text.split("ST*")[1].split("*")[0].strip("~\r\n")
        except Exception:
            pass

        with tempfile.NamedTemporaryFile(delete=False, suffix=".edi") as f:
            f.write(raw_edi)
            temp_path = f.name

        try:
            json_result = edi_to_json(temp_path, editype="x12", messagetype=messagetype)
            # In a real implementation, we would extract sender, receiver, etc from json_result
            return ParsedEdiPayload(
                sender_id="UNKNOWN",
                receiver_id="UNKNOWN",
                interchange_control_number="UNKNOWN",
                transactions=[
                    TransactionSet(
                        transaction_type=messagetype,
                        control_number="UNKNOWN",
                        data=json.loads(json_result),
                    )
                ],
            )
        except Exception as e:
            raise TranslationError(f"Translation failed: {e}") from e
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
