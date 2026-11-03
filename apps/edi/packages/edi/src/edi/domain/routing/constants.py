"""Routing Domain Constants."""

from typing import Final

# Used in OutboundEdiHeader.transaction_type to mean "accept any transaction
# type and resolve it from the payload at transform-time".
WILDCARD_TRANSACTION_TYPE: Final[str] = "*"
