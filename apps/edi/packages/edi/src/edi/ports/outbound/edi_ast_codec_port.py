from typing import Protocol

from seedwork.domain.types import JsonDict

from edi.domain.transaction.enums import EdiStandard, EdiTransactionType


class EdiAstCodecPort(Protocol):
    """Port for parsing raw EDI bytes into an AST dictionary and serializing an AST back to EDI."""

    def get_raw_ast(
        self,
        raw_edi: bytes,
        editype: str = EdiStandard.X12,
        messagetype: str = EdiTransactionType.ENVELOPE,
    ) -> tuple[JsonDict, list[str]]: ...

    def serialize_to_edi(
        self,
        ast_dict: JsonDict | list[JsonDict],
        standard: str = EdiStandard.X12,
    ) -> tuple[str, list[str]]: ...
