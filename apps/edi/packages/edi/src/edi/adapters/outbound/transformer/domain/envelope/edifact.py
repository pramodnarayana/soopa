import datetime
import uuid
from typing import Any

from edi.adapters.outbound.transformer.domain.ast_utils import ASTUtils
from edi.adapters.outbound.transformer.domain.envelope.base import BaseEnvelopeBuilder


class EdifactEnvelopeBuilder(BaseEnvelopeBuilder):
    @classmethod
    def _build_unb_segment(
        cls, route_config: dict[str, Any], now: datetime.datetime, unb05: str
    ) -> dict[str, Any]:
        unb_sender_id = route_config.get("isa_sender_id", "UNKNOWN")
        unb_receiver_id = route_config.get("isa_receiver_id", "UNKNOWN")
        version = route_config.get("default_version", "4")
        environment = "1" if route_config.get("environment") == "T" else ""

        unb = {
            "S001.01": "UNOA",
            "S001.02": version,
            "S002.01": unb_sender_id,
            "S002.02": route_config.get("isa_sender_qualifier", "14"),
            "S003.01": unb_receiver_id,
            "S003.02": route_config.get("isa_receiver_qualifier", "14"),
            "S004.01": now.strftime("%y%m%d"),
            "S004.02": now.strftime("%H%M"),
            "0020": unb05,
        }
        if environment:
            unb["S005.01"] = "XX"

        return unb

    @classmethod
    def _wrap_transactions(
        cls, transactions: list[dict[str, Any]], transaction_type: str
    ) -> list[dict[str, Any]]:
        processed_transactions = []
        for i, txn in enumerate(transactions, start=1):
            new_txn = {}
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
                new_txn["UNT"] = {
                    "UNT01": str(segment_count),
                    "UNT02": new_txn.get("UNH", {}).get("UNH01", f"{i:04d}"),
                }

            processed_transactions.append(new_txn)
        return processed_transactions

    @classmethod
    def build(
        cls, route_config: dict[str, Any], payload: dict[str, Any] | list[dict[str, Any]]
    ) -> dict[str, Any]:
        now = datetime.datetime.now(datetime.UTC)
        transactions = payload if isinstance(payload, list) else [payload]
        transaction_type = route_config.get("transaction_type", "UNKNOWN")

        # Generation values
        unb05 = str(uuid.uuid4().int % 1000000000).zfill(9)

        # Build segments
        unb_segment = cls._build_unb_segment(route_config, now, unb05)
        processed_transactions = cls._wrap_transactions(transactions, transaction_type)

        unz_segment = {"UNZ01": str(len(processed_transactions)), "UNZ02": unb05}

        # Orchestrate the final AST structure
        return {
            "interchange_UNB": [
                {"UNB": unb_segment, "transaction_UNH": processed_transactions, "UNZ": unz_segment}
            ]
        }
