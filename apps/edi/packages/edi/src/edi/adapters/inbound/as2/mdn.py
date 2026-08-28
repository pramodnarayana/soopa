"""
AS2 MDN module — backward-compatible re-export shim.

MDN generation logic has been canonically moved to edi.domain.services.as2_protocol.
This module re-exports the public API so adapter-internal callers continue to work.
"""

# Re-export from canonical domain locations
from edi.domain.models.as2 import AS2MDN, AS2Message, Disposition, MDNResponse
from edi.domain.services.as2_protocol import (
    build_mdn,
    calculate_mic,
    generate_mdn,
    parse_mdn,
)

__all__ = [
    "AS2MDN",
    "AS2Message",
    "Disposition",
    "MDNResponse",
    "build_mdn",
    "calculate_mic",
    "generate_mdn",
    "parse_mdn",
]
