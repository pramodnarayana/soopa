import datetime
from typing import cast

from edi.adapters.outbound.transformer.domain.ast_utils import ASTUtils
from edi.adapters.outbound.transformer.domain.envelope.base import BaseEnvelopeBuilder
from edi.domain.exceptions import InvalidMessageFormatError
from edi.domain.models.headers import EdiEnvelopeHeaders
from edi.domain.types import AstNode, JsonDict, JsonValue

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
        cls, edi_headers: EdiEnvelopeHeaders, now: datetime.datetime, isa13: str
    ) -> AstNode:
        isa_sender_qualifier = edi_headers.isa_sender_qualifier or "ZZ"
        isa_sender_id_raw = (edi_headers.isa_sender_id or "").strip()
        isa_receiver_id_raw = (edi_headers.isa_receiver_id or "").strip()
        if not isa_sender_id_raw or not isa_receiver_id_raw:
            raise InvalidMessageFormatError(
                "Route config missing required ISA sender or receiver ID"
            )

        isa_sender_id = isa_sender_id_raw.ljust(15)
        isa_receiver_qualifier = edi_headers.isa_receiver_qualifier or "ZZ"
        isa_receiver_id = isa_receiver_id_raw.ljust(15)

        version = edi_headers.default_version or "004010"
        isa_version = version[:5] if len(version) >= 5 else "00401"
        environment = edi_headers.isa_usage_indicator or "P"

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
        cls, edi_headers: EdiEnvelopeHeaders, now: datetime.datetime, gs06: str
    ) -> AstNode:
        transaction_type = edi_headers.transaction_type or "XX"

        isa_sender_id = edi_headers.isa_sender_id or ""
        isa_receiver_id = edi_headers.isa_receiver_id or ""
        gs_sender_id = edi_headers.gs_sender_id or isa_sender_id
        gs_receiver_id = edi_headers.gs_receiver_id or isa_receiver_id

        version = edi_headers.default_version or "004010"
        gs01 = str(X12_GS01_MAPPING.get(transaction_type, "XX"))

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
        cls, transactions: list[AstNode], transaction_type: str
    ) -> list[AstNode]:
        processed_transactions = []
        for i, txn in enumerate(transactions, start=1):
            new_txn: JsonDict = {}
            if "ST" not in txn:
                new_txn["ST"] = {"ST01": transaction_type, "ST02": f"{i:04d}"}

            # Copy all business data in order
            for k, v in txn.items():
                if k not in new_txn:
                    new_txn[k] = v

            if "SE" not in new_txn:
                # Calculate segment count (existing + SE)
                segment_count = ASTUtils.count_segments(new_txn) + 1
                st = new_txn.get("ST")
                se02 = st.get("ST02", f"{i:04d}") if isinstance(st, dict) else f"{i:04d}"
                new_txn["SE"] = {
                    "SE01": str(segment_count),
                    "SE02": se02,
                }

            processed_transactions.append(new_txn)
        return processed_transactions

    @classmethod
    def build(cls, edi_headers: EdiEnvelopeHeaders, payload: AstNode | list[AstNode]) -> AstNode:
        now = datetime.datetime.now(datetime.UTC)
        transactions = payload if isinstance(payload, list) else [payload]
        transaction_type = edi_headers.transaction_type or "UNKNOWN"

        # Generation values
        monotonic_counter = int(now.timestamp() * 1000) % 1000000000
        isa13 = f"{monotonic_counter:09d}"
        gs06 = str(monotonic_counter)

        # Build segments
        isa_segment = cls._build_isa_segment(edi_headers, now, isa13)
        gs_segment = cls._build_gs_segment(edi_headers, now, gs06)
        processed_transactions = cls._wrap_transactions(transactions, transaction_type)

        ge_segment: JsonDict = {"GE01": str(len(processed_transactions)), "GE02": gs06}
        iea_segment: JsonDict = {"IEA01": "1", "IEA02": isa13}

        # Orchestrate the final AST structure
        return {
            "interchange_ISA": [
                {
                    "ISA": isa_segment,
                    "group_GS": [
                        {
                            "GS": gs_segment,
                            "transaction_ST": cast(list[JsonValue], processed_transactions),
                            "GE": ge_segment,
                        }
                    ],
                    "IEA": iea_segment,
                }
            ]
        }
