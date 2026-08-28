"""
AS2 adapter package.

Domain models (AS2Message, AS2MDN, OutboundAS2Message) live in edi.domain.models.as2.
This package re-exports them for backward compatibility within the adapters layer,
and exposes adapter-specific builders/parsers that depend on crypto infrastructure.
"""

from edi.domain.models.as2 import AS2MDN, AS2Message, Disposition, MDNResponse, OutboundAS2Message

from .builder import build_outbound_message
from .mdn import generate_mdn
from .parser import parse_as2_request, parse_mdn

__all__ = [
    "AS2MDN",
    "AS2Message",
    "Disposition",
    "MDNResponse",
    "OutboundAS2Message",
    "build_outbound_message",
    "generate_mdn",
    "parse_as2_request",
    "parse_mdn",
]
