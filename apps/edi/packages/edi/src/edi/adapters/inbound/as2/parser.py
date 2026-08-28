"""
AS2 parser module — backward-compatible re-export shim.

Parsing logic has been canonically moved to edi.domain.services.as2_protocol.
This module re-exports the public API so adapter-internal callers continue to work.
"""

# Re-export from canonical domain locations
from edi.domain.models.as2 import AS2MDN, AS2Message
from edi.domain.services.as2_protocol import parse_as2_request, parse_mdn

__all__ = ["AS2MDN", "AS2Message", "parse_as2_request", "parse_mdn"]
