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
# Kept here because EdiIdPrefix drives repository ID generation and is referenced
# in many adapters — it is not a business-status enum, it is a naming convention.
from enum import StrEnum

from edi.domain.enums import (
    EdiEventType,
    UcpEventType,
    WebhookEventType,
)


class EdiIdPrefix(StrEnum):
    CP_OUTBOX = "edi_cp_ob"
    DP_OUTBOX = "edi_dp_ob"
    AS2_SERVER = "edi_as2"
    AS2_PARTNER = "edi_as2_tp"
    AS2_PARTNERSHIP = "edi_as2_pship"
    SFTP_PARTNER = "edi_sftp"
    WEBHOOK = "edi_dp_wh"
    INBOUND_ROUTE = "edi_inb_rt"
    OUTBOUND_HEADER = "edi_outb_hdr"
    OUTBOUND_ROUTE = "edi_outb_rt"
    EDI_MESSAGE = "edi_msg"
    EDI_JSON = "edi_json"
    API_GATEWAY = "edi_api_gw"


# ── Aggregated provisioning event set ────────────────────────────────────────
ProvisioningEventType = EdiEventType | WebhookEventType | UcpEventType

ALL_PROVISIONING_EVENT_TYPES = (
    [e.value for e in EdiEventType]
    + [e.value for e in WebhookEventType]
    + [e.value for e in UcpEventType]
)
