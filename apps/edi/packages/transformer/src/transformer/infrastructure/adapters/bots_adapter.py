import json
import logging

from transformer.application.ports import EDITransformerPort
from transformer.domain.exceptions import TransformationError
from transformer.domain.models import JsonDict, ParsedEdiPayload, TransactionSet

logger = logging.getLogger(__name__)


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
        self, raw_edi: bytes, editype: str = "x12", messagetype: str = "envelope"
    ) -> tuple[JsonDict, list[str]]:
        """Returns the raw AST dictionary and any validation errors."""
        try:
            from bots_core.facade import edi_to_json

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
        except Exception as e:
            logger.exception("Bots error during AST generation")
            error_msg = str(e)
            parsed_errors = []

            if error_msg.startswith("[") or "Details:" in error_msg:
                parsed_errors = [line.strip() for line in error_msg.split("\n") if line.strip()]

            raise TransformationError(f"AST generation failed: {e}", errors=parsed_errors) from e

    def serialize_to_edi(self, ast_dict: JsonDict, standard: str = "x12") -> tuple[str, list[str]]:
        """
        Serializes a JSON AST back into raw EDI format using the Bots engine.
        """
        try:
            from bots_core.facade import json_to_edi

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

    async def transform(
        self, raw_edi: bytes, editype: str = "x12", messagetype: str = "envelope"
    ) -> ParsedEdiPayload:
        """
        Executes the Bots translation process.

        This transforms raw X12/EDIFACT bytes into our pristine domain model.
        """
        logger.info(f"Invoking stateless Bots adapter with {len(raw_edi)} bytes of payload")

        # Validate payload before attempting to load backend
        if not raw_edi:
            raise TransformationError("Payload is completely empty, Bots engine aborted.")

        import asyncio

        try:
            ast_dict, errors = await asyncio.to_thread(
                self.get_raw_ast, raw_edi, editype=editype, messagetype=messagetype
            )
            if errors:
                raise TransformationError(
                    f"Validation failed with {len(errors)} errors", errors=errors
                )

            sender_id = "UNKNOWN"
            receiver_id = "UNKNOWN"
            interchange_control_number = "UNKNOWN"
            transactions = []

            # Extract X12 metadata
            for isa_node in self._get_list_of_dicts(ast_dict, "interchange_ISA"):
                isa = self._get_dict(isa_node, "ISA")
                if isa:
                    sender_id = self._get_str(isa, "ISA06", "UNKNOWN")
                    receiver_id = self._get_str(isa, "ISA08", "UNKNOWN")
                    interchange_control_number = self._get_str(isa, "ISA13", "UNKNOWN")

                    for gs_node in self._get_list_of_dicts(isa_node, "group_GS"):
                        gs_record = self._get_dict(gs_node, "GS")
                        gs_sender = "UNKNOWN"
                        gs_receiver = "UNKNOWN"
                        if gs_record:
                            gs_sender = self._get_str(gs_record, "GS02", "UNKNOWN")
                            gs_receiver = self._get_str(gs_record, "GS03", "UNKNOWN")

                        for st_node in self._get_list_of_dicts(gs_node, "transaction_ST"):
                            st_record = self._get_dict(st_node, "ST")
                            if st_record:
                                transactions.append(
                                    TransactionSet(
                                        transaction_type=self._get_str(
                                            st_record, "ST01", "UNKNOWN"
                                        ),
                                        control_number=self._get_str(st_record, "ST02", "UNKNOWN"),
                                        gs_sender_id=gs_sender,
                                        gs_receiver_id=gs_receiver,
                                        data=st_node,
                                    )
                                )

            # Extract EDIFACT metadata
            for unb_node in self._get_list_of_dicts(ast_dict, "interchange_UNB"):
                unb = self._get_dict(unb_node, "UNB")
                if unb:
                    sender_id = self._get_str(unb, "S002.0004", "UNKNOWN")
                    receiver_id = self._get_str(unb, "S003.0010", "UNKNOWN")
                    interchange_control_number = self._get_str(unb, "0020", "UNKNOWN")

                for unh_node in self._get_list_of_dicts(unb_node, "transaction_UNH"):
                    unh = self._get_dict(unh_node, "UNH")
                    if unh:
                        unh02 = self._get_dict(unh, "UNH02")
                        transactions.append(
                            TransactionSet(
                                transaction_type=self._get_str(unh02, "UNH02.01", "UNKNOWN"),
                                control_number=self._get_str(unh, "UNH01", "UNKNOWN"),
                                data=unh_node,
                            )
                        )

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
