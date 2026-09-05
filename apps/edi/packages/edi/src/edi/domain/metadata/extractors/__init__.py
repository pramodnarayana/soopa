"""
Registry for all transaction-specific metadata extractors.
"""

from edi.domain.enums import EdiTransactionType
from edi.domain.metadata.extractors import (
    x12_204,
    x12_210,
    x12_214,
    x12_810,
    x12_850,
    x12_990,
    x12_997,
)

EXTRACTOR_CONFIG: dict[str, dict[str, str]] = {
    EdiTransactionType.X12_850: x12_850.FIELD_MAPPING,
    EdiTransactionType.X12_810: x12_810.FIELD_MAPPING,
    EdiTransactionType.X12_204: x12_204.FIELD_MAPPING,
    EdiTransactionType.X12_990: x12_990.FIELD_MAPPING,
    EdiTransactionType.X12_214: x12_214.FIELD_MAPPING,
    EdiTransactionType.X12_210: x12_210.FIELD_MAPPING,
    EdiTransactionType.X12_997: x12_997.FIELD_MAPPING,
}
