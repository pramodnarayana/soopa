"""Registry for all transaction-specific metadata extractors."""

from edi.domain.transaction.enums import EdiTransactionType

X12_850_MAPPING: dict[str, str] = {
    "po_number": "$..BEG.BEG03",
    "po_date": "$..BEG.BEG05",
    "business_reference": "$..BEG.BEG03",
}

X12_810_MAPPING: dict[str, str] = {
    "invoice_number": "$..BIG.BIG02",
    "po_number": "$..BIG.BIG04",
    "business_reference": "$..BIG.BIG02",
}

X12_204_MAPPING: dict[str, str] = {
    "load_number": "$..B2.B204",
    "business_reference": "$..B2.B204",
}

X12_990_MAPPING: dict[str, str] = {
    "load_number": "$..B1.B102",
    "business_reference": "$..B1.B102",
}

X12_214_MAPPING: dict[str, str] = {
    "load_number": "$..B10.B1002",
    "business_reference": "$..B10.B1002",
}

X12_210_MAPPING: dict[str, str] = {
    "invoice_number": "$..B3.B302",
    "business_reference": "$..B3.B302",
}

X12_997_MAPPING: dict[str, str] = {
    "group_control_number": "$..AK1.AK102",
    "business_reference": "$..AK1.AK102",
}

EXTRACTOR_CONFIG: dict[str, dict[str, str]] = {
    EdiTransactionType.X12_850: X12_850_MAPPING,
    EdiTransactionType.X12_810: X12_810_MAPPING,
    EdiTransactionType.X12_204: X12_204_MAPPING,
    EdiTransactionType.X12_990: X12_990_MAPPING,
    EdiTransactionType.X12_214: X12_214_MAPPING,
    EdiTransactionType.X12_210: X12_210_MAPPING,
    EdiTransactionType.X12_997: X12_997_MAPPING,
}

__all__ = [
    "EXTRACTOR_CONFIG",
    "X12_204_MAPPING",
    "X12_210_MAPPING",
    "X12_214_MAPPING",
    "X12_810_MAPPING",
    "X12_850_MAPPING",
    "X12_990_MAPPING",
    "X12_997_MAPPING",
]
