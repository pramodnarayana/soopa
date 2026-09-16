import asyncio
import json

import structlog

from edi.adapters.outbound.transformer.application.ports import EDITransformerPort
from edi.adapters.outbound.transformer.domain.exceptions import TransformationError
from edi.adapters.outbound.transformer.domain.models import (
    JsonDict,
    ParsedEdiPayload,
    TransactionSet,
)
from edi.core.bots.facade import edi_to_json, json_to_edi
from edi.domain.enums import EdiStandard, EdiTransactionType
from edi.domain.exceptions import InvalidMessageFormatError

logger = structlog.get_logger(__name__)


class BotsEDIAdapter(EDITransformerPort):
    """
    Adapter to run the vendored BOTS EDI translation engine natively in-memory.
    No sub-processes, no external cron jobs.
    """

    def __init__(self) -> None:
        pass

    @staticmethod
    def _get_list_of_dicts(data: JsonDict, key: str) -> list[JsonDict]:
        val = data.get(key)
        if isinstance(val, dict):
            return [val]
        if isinstance(val, list):
            return [v for v in val if isinstance(v, dict)]
        return []

    @staticmethod
    def _get_dict(data: JsonDict, key: str) -> JsonDict:
        val = data.get(key)
        if isinstance(val, dict):
            return val
        return {}

    @staticmethod
    def _get_str(data: JsonDict, key: str, default: str = "") -> str:
        val = data.get(key)
        if val is None or val == "":
            return default
        return str(val).strip()

    def get_raw_ast(
        self,
        raw_edi: bytes,
        editype: str = EdiStandard.X12,
        messagetype: str = EdiTransactionType.ENVELOPE,
    ) -> tuple[JsonDict, list[str]]:
        """Returns the raw AST dictionary and any validation errors."""
        try:
            json_result = edi_to_json(
                raw_edi=raw_edi, editype=editype, messagetype=messagetype, return_errors=True
            )
            data = json.loads(json_result)
            ast_dict = data.get("ast", {})
            errors = data.get("errors", [])
            # Clean up the error strings
            parsed_errors = [
                line.strip() for err in errors for line in str(err).split("\n") if line.strip()
            ]
            return ast_dict, parsed_errors
        except ValueError as e:
            error_msg = str(e)
            parsed_errors = [line.strip() for line in error_msg.split("\n") if line.strip()]
            logger.warning("bots_adapter.validation_failed", error=error_msg)
            raise TransformationError(f"AST generation failed: {e}", errors=parsed_errors) from e
        except Exception as e:
            logger.exception("bots_adapter.system_error")
            raise TransformationError(f"AST generation failed: {e}", errors=[]) from e

    def serialize_to_edi(
        self, ast_dict: JsonDict, standard: str = EdiStandard.X12
    ) -> tuple[str, list[str]]:
        """
        Serializes a JSON AST back into raw EDI format using the Bots engine.
        """
        try:
            ast_json_str = json.dumps(ast_dict)
            result = json_to_edi(
                json_ast=ast_json_str, editype=standard, messagetype="envelope", return_errors=True
            )

            data = json.loads(result)
            edi_str = data.get("edi", "")
            errors = data.get("errors", [])

            # Clean up the error strings
            parsed_errors = [
                line.strip() for err in errors for line in str(err).split("\n") if line.strip()
            ]
            return edi_str, parsed_errors
        except Exception as e:
            logger.exception("Bots error during EDI serialization")
            raise TransformationError(f"EDI serialization failed: {e}") from e

    def _extract_x12_metadata(
        self, ast_dict: JsonDict
    ) -> tuple[str, str, str, list[TransactionSet]]:
        sender_id: str | None = None
        receiver_id: str | None = None
        interchange_control_number: str | None = None
        transactions = []

        for isa_node in self._get_list_of_dicts(ast_dict, "interchange_ISA"):
            isa = self._get_dict(isa_node, "ISA")
            if isa:
                sender_id = self._get_str(isa, "ISA06")
                receiver_id = self._get_str(isa, "ISA08")
                interchange_control_number = self._get_str(isa, "ISA13")

                for gs_node in self._get_list_of_dicts(isa_node, "group_GS"):
                    gs_record = self._get_dict(gs_node, "GS")
                    gs_sender: str | None = None
                    gs_receiver: str | None = None
                    if gs_record:
                        gs_sender = self._get_str(gs_record, "GS02")
                        gs_receiver = self._get_str(gs_record, "GS03")

                    for st_node in self._get_list_of_dicts(gs_node, "transaction_ST"):
                        st_record = self._get_dict(st_node, "ST")
                        if st_record:
                            txn_type = self._get_str(st_record, "ST01")
                            if not txn_type:
                                raise InvalidMessageFormatError(
                                    "Missing transaction type (ST01) in X12 payload"
                                )
                            transactions.append(
                                TransactionSet(
                                    transaction_type=txn_type,
                                    control_number=self._get_str(st_record, "ST02") or "",
                                    gs_sender_id=gs_sender,
                                    gs_receiver_id=gs_receiver,
                                    data=st_node,
                                )
                            )

        if not sender_id or not receiver_id:
            raise InvalidMessageFormatError(
                "Invalid X12 Envelope: Missing ISA sender or receiver ID"
            )
        if not interchange_control_number:
            raise InvalidMessageFormatError("Invalid X12 Envelope: Missing ISA control number")

        return sender_id, receiver_id, interchange_control_number, transactions

    def _extract_edifact_metadata(
        self, ast_dict: JsonDict
    ) -> tuple[str, str, str, list[TransactionSet]]:
        sender_id: str | None = None
        receiver_id: str | None = None
        interchange_control_number: str | None = None
        transactions = []

        for unb_node in self._get_list_of_dicts(ast_dict, "interchange_UNB"):
            unb = self._get_dict(unb_node, "UNB")
            if unb:
                sender_id = self._get_str(unb, "S002.0004")
                receiver_id = self._get_str(unb, "S003.0010")
                interchange_control_number = self._get_str(unb, "0020")

            for unh_node in self._get_list_of_dicts(unb_node, "transaction_UNH"):
                unh = self._get_dict(unh_node, "UNH")
                if unh:
                    unh02 = self._get_dict(unh, "UNH02")
                    txn_type = self._get_str(unh02, "UNH02.01") if unh02 else None
                    if not txn_type:
                        raise InvalidMessageFormatError(
                            "Missing transaction type (UNH02.01) in EDIFACT payload"
                        )
                    transactions.append(
                        TransactionSet(
                            transaction_type=txn_type,
                            control_number=self._get_str(unh, "UNH01") or "",
                            data=unh_node,
                        )
                    )

        if not sender_id or not receiver_id:
            raise InvalidMessageFormatError(
                "Invalid EDIFACT Envelope: Missing UNB sender or receiver ID"
            )
        if not interchange_control_number:
            raise InvalidMessageFormatError("Invalid EDIFACT Envelope: Missing UNB control number")

        return sender_id, receiver_id, interchange_control_number, transactions

    async def transform(
        self,
        raw_edi: bytes,
        editype: str = EdiStandard.X12,
        messagetype: str = EdiTransactionType.ENVELOPE,
    ) -> ParsedEdiPayload:
        """
        Executes the Bots translation process.

        This transforms raw X12/EDIFACT bytes into our pristine domain model.
        """
        logger.info(
            "bots_adapter.transform_started",
            payload_length=len(raw_edi),
        )

        # Validate payload before attempting to load backend
        if not raw_edi:
            raise TransformationError("Payload is completely empty, Bots engine aborted.")

        try:
            ast_dict, errors = await asyncio.to_thread(
                self.get_raw_ast, raw_edi, editype=editype, messagetype=messagetype
            )
            if errors:
                raise TransformationError(
                    f"Validation failed with {len(errors)} errors", errors=errors
                )

            extractors = {
                "edifact": self._extract_edifact_metadata,
                "x12": self._extract_x12_metadata,
            }
            extractor = extractors.get(editype.lower())
            if not extractor:
                raise TransformationError(
                    f"Unsupported EDI standard for metadata extraction: {editype}"
                )

            sender_id, receiver_id, interchange_control_number, transactions = extractor(ast_dict)

            return ParsedEdiPayload(
                sender_id=sender_id,
                receiver_id=receiver_id,
                interchange_control_number=interchange_control_number,
                transactions=transactions,
            )
        except TransformationError:
            raise
        except Exception as e:
            raise TransformationError(f"Translation failed: {e}") from e
