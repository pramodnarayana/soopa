"""
EDI Domain Constants
====================

Non-enumeration constants for the EDI bounded context.
All StrEnum definitions live in ``edi.domain.enums``.
"""

from typing import Final

# ── Route configuration sentinels ────────────────────────────────────────────
# Used in OutboundEdiHeader.transaction_type to mean "accept any transaction
# type and resolve it from the payload at transform-time".
WILDCARD_TRANSACTION_TYPE: Final[str] = "*"

# ── ID prefixes ──────────────────────────────────────────────────────────────
# Moved to core/platform/packages/seedwork/src/seedwork/constants.py (DomainIdPrefix)

from edi.domain.enums import (
    EdiEventType,
    UcpEventType,
    WebhookEventType,
)

# ── Aggregated provisioning event set ────────────────────────────────────────
ProvisioningEventType = EdiEventType | WebhookEventType | UcpEventType

ALL_PROVISIONING_EVENT_TYPES = (
    [e.value for e in EdiEventType]
    + [e.value for e in WebhookEventType]
    + [e.value for e in UcpEventType]
)
