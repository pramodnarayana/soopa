import datetime
from typing import Any

from edi.adapters.outbound.transformer.domain.ast_utils import ASTUtils
from edi.adapters.outbound.transformer.domain.envelope.base import BaseEnvelopeBuilder

X12_GS01_MAPPING = {
    "850": "PO",
    "810": "IN",
    "856": "SH",
    "855": "PR",
    "846": "IB",
    "832": "SC",
    "204": "SM",
    "210": "IM",
    "214": "QM",
    "990": "GF",
    "997": "FA",
}


class X12EnvelopeBuilder(BaseEnvelopeBuilder):
    @classmethod
    def _build_isa_segment(
        cls, route_config: dict[str, Any], now: datetime.datetime, isa13: str
    ) -> dict[str, Any]:
        isa_sender_qualifier = route_config.get("isa_sender_qualifier") or "ZZ"
        isa_sender_id = str(route_config.get("isa_sender_id", "UNKNOWN")).ljust(15)
        isa_receiver_qualifier = route_config.get("isa_receiver_qualifier") or "ZZ"
        isa_receiver_id = str(route_config.get("isa_receiver_id", "UNKNOWN")).ljust(15)

        version = route_config.get("default_version", "004010")
        isa_version = version[:5] if len(version) >= 5 else "00401"
        environment = route_config.get("environment", "P")

        return {
            "ISA01": "00",
            "ISA02": "          ",
            "ISA03": "00",
            "ISA04": "          ",
            "ISA05": isa_sender_qualifier,
            "ISA06": isa_sender_id,
            "ISA07": isa_receiver_qualifier,
            "ISA08": isa_receiver_id,
            "ISA09": now.strftime("%y%m%d"),
            "ISA10": now.strftime("%H%M"),
            "ISA11": "U",
            "ISA12": isa_version,
            "ISA13": isa13,
            "ISA14": "0",
            "ISA15": environment,
        }

    @classmethod
    def _build_gs_segment(
        cls, route_config: dict[str, Any], now: datetime.datetime, gs06: str
    ) -> dict[str, Any]:
        transaction_type = route_config.get("transaction_type", "UNKNOWN")
        gs_sender_id = route_config.get("gs_sender_id") or route_config.get(
            "isa_sender_id", "UNKNOWN"
        )
        gs_receiver_id = route_config.get("gs_receiver_id") or route_config.get(
            "isa_receiver_id", "UNKNOWN"
        )
        version = route_config.get("default_version", "004010")
        gs01 = X12_GS01_MAPPING.get(transaction_type, "XX")

        return {
            "GS01": gs01,
            "GS02": gs_sender_id,
            "GS03": gs_receiver_id,
            "GS04": now.strftime("%Y%m%d"),
            "GS05": now.strftime("%H%M"),
            "GS06": gs06,
            "GS07": "X",
            "GS08": version,
        }

    @classmethod
    def _wrap_transactions(
        cls, transactions: list[dict[str, Any]], transaction_type: str
    ) -> list[dict[str, Any]]:
        processed_transactions = []
        for i, txn in enumerate(transactions, start=1):
            new_txn = {}
            if "ST" not in txn:
                new_txn["ST"] = {"ST01": transaction_type, "ST02": f"{i:04d}"}

            # Copy all business data in order
            for k, v in txn.items():
                if k not in new_txn:
                    new_txn[k] = v

            if "SE" not in new_txn:
                # Calculate segment count (existing + SE)
                segment_count = ASTUtils.count_segments(new_txn) + 1
                new_txn["SE"] = {
                    "SE01": str(segment_count),
                    "SE02": new_txn.get("ST", {}).get("ST02", f"{i:04d}"),
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
        monotonic_counter = int(now.timestamp() * 1000) % 1000000000
        isa13 = f"{monotonic_counter:09d}"
        gs06 = str(monotonic_counter)

        # Build segments
        isa_segment = cls._build_isa_segment(route_config, now, isa13)
        gs_segment = cls._build_gs_segment(route_config, now, gs06)
        processed_transactions = cls._wrap_transactions(transactions, transaction_type)

        ge_segment = {"GE01": str(len(processed_transactions)), "GE02": gs06}

        iea_segment = {"IEA01": "1", "IEA02": isa13}

        # Orchestrate the final AST structure
        return {
            "interchange_ISA": [
                {
                    "ISA": isa_segment,
                    "group_GS": [
                        {
                            "GS": gs_segment,
                            "transaction_ST": processed_transactions,
                            "GE": ge_segment,
                        }
                    ],
                    "IEA": iea_segment,
                }
            ]
        }
