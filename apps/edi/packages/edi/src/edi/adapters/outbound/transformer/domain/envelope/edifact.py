import datetime
import uuid
from typing import cast

from seedwork.domain.types import JsonValue

from edi.adapters.outbound.transformer.domain.ast_utils import ASTUtils
from edi.adapters.outbound.transformer.domain.envelope.base import BaseEnvelopeBuilder
from edi.domain.types import AstNode


class EdifactEnvelopeBuilder(BaseEnvelopeBuilder):
    @classmethod
    def _build_unb_segment(
        cls, route_config: dict[str, JsonValue], now: datetime.datetime, unb05: str
    ) -> AstNode:
        unb_sender_id = str(route_config.get("isa_sender_id", "UNKNOWN"))
        unb_receiver_id = str(route_config.get("isa_receiver_id", "UNKNOWN"))
        version = str(route_config.get("default_version", "4"))
        environment = "1" if str(route_config.get("environment", "")) == "T" else ""

        unb: dict[str, JsonValue] = {
            "S001.01": "UNOA",
            "S001.02": version,
            "S002.01": unb_sender_id,
            "S002.02": str(route_config.get("isa_sender_qualifier", "14")),
            "S003.01": unb_receiver_id,
            "S003.02": str(route_config.get("isa_receiver_qualifier", "14")),
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
            new_txn: dict[str, JsonValue] = {}
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
                unt02 = (
                    cast(dict, unh).get("UNH01", f"{i:04d}")
                    if isinstance(unh, dict)
                    else f"{i:04d}"
                )
                new_txn["UNT"] = {
                    "UNT01": str(segment_count),
                    "UNT02": unt02,
                }

            processed_transactions.append(new_txn)
        return processed_transactions

    @classmethod
    def build(cls, route_config: dict[str, JsonValue], payload: AstNode | list[AstNode]) -> AstNode:
        now = datetime.datetime.now(datetime.UTC)
        transactions = payload if isinstance(payload, list) else [payload]
        transaction_type = str(route_config.get("transaction_type", "UNKNOWN"))

        # Generation values
        unb05 = str(uuid.uuid4().int % 1000000000).zfill(9)

        # Build segments
        unb_segment = cls._build_unb_segment(route_config, now, unb05)
        processed_transactions = cls._wrap_transactions(transactions, transaction_type)

        unz_segment: dict[str, JsonValue] = {
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
