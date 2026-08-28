"""
AS2 message module — backward-compatible re-export shim.

Domain models have been canonically moved to edi.domain.models.as2.
This module re-exports them so any remaining adapter-internal references
continue to work without modification.
"""

# Re-export from canonical domain location
from edi.domain.models.as2 import AS2MDN, AS2Message

__all__ = ["AS2MDN", "AS2Message"]
