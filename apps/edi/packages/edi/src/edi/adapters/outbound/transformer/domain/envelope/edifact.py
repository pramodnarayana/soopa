import datetime
import uuid
from typing import cast

from edi.adapters.outbound.transformer.domain.ast_utils import ASTUtils
from edi.adapters.outbound.transformer.domain.envelope.base import BaseEnvelopeBuilder
from edi.domain.exceptions import InvalidMessageFormatError
from edi.domain.models.headers import EdiEnvelopeHeaders
from edi.domain.types import AstNode, JsonDict, JsonValue


class EdifactEnvelopeBuilder(BaseEnvelopeBuilder):
    @classmethod
    def _build_unb_segment(
        cls, edi_headers: EdiEnvelopeHeaders, now: datetime.datetime, unb05: str
    ) -> AstNode:
        unb_sender_id = (edi_headers.isa_sender_id or "").strip()
        unb_receiver_id = (edi_headers.isa_receiver_id or "").strip()
        if not unb_sender_id or not unb_receiver_id:
            raise InvalidMessageFormatError(
                "Route config missing required UNB sender or receiver ID"
            )
        version = edi_headers.default_version or "4"
        environment = "1" if edi_headers.isa_usage_indicator == "T" else ""

        unb: JsonDict = {
            "S001.01": "UNOA",
            "S001.02": version,
            "S002.01": unb_sender_id,
            "S002.02": edi_headers.isa_sender_qualifier or "14",
            "S003.01": unb_receiver_id,
            "S003.02": edi_headers.isa_receiver_qualifier or "14",
            "S004.01": now.strftime("%y%m%d"),
            "S004.02": now.strftime("%H%M"),
            "0020": unb05,
        }
        if environment:
            unb["S005.01"] = "XX"

        return unb

    @classmethod
    def _wrap_transactions(
        cls, transactions: list[AstNode], transaction_type: str
    ) -> list[AstNode]:
        processed_transactions = []
        for i, txn in enumerate(transactions, start=1):
            new_txn: JsonDict = {}
            if "UNH" not in txn:
                new_txn["UNH"] = {
                    "UNH01": f"{i:04d}",
                    "UNH02": {
                        "UNH02.01": transaction_type,
                        "UNH02.02": "D",
                        "UNH02.03": "96A",
                        "UNH02.04": "UN",
                    },
                }

            for k, v in txn.items():
                if k not in new_txn:
                    new_txn[k] = v

            if "UNT" not in new_txn:
                segment_count = ASTUtils.count_segments(new_txn) + 1
                unh = new_txn.get("UNH")
                unt02 = unh.get("UNH01", f"{i:04d}") if isinstance(unh, dict) else f"{i:04d}"
                new_txn["UNT"] = {
                    "UNT01": str(segment_count),
                    "UNT02": unt02,
                }

            processed_transactions.append(new_txn)
        return processed_transactions

    @classmethod
    def build(cls, edi_headers: EdiEnvelopeHeaders, payload: AstNode | list[AstNode]) -> AstNode:
        now = datetime.datetime.now(datetime.UTC)
        transactions = payload if isinstance(payload, list) else [payload]
        transaction_type = edi_headers.transaction_type or "UNKNOWN"

        # Generation values
        unb05 = str(uuid.uuid4().int % 1000000000).zfill(9)

        # Build segments
        unb_segment = cls._build_unb_segment(edi_headers, now, unb05)
        processed_transactions = cls._wrap_transactions(transactions, transaction_type)

        unz_segment: JsonDict = {
            "UNZ01": str(len(processed_transactions)),
            "UNZ02": unb05,
        }

        # Orchestrate the final AST structure
        return {
            "interchange_UNB": [
                {
                    "UNB": unb_segment,
                    "transaction_UNH": cast(list[JsonValue], processed_transactions),
                    "UNZ": unz_segment,
                }
            ]
        }
