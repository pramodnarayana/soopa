"""EDI Domain Constants and Identifier Prefixes."""

from enum import StrEnum


class EdiConstants(StrEnum):
    OUTBOX_CHANNEL = "edi_outbox_channel"
    EDI_APP_SLUG = "edi"


class EdiIdPrefix(StrEnum):
    """Domain-specific ID prefixes for EDI aggregates and entities."""

    TENANT = "iam_ten"
    EDI_CP_OUTBOX = "edi_cp_ob"
    EDI_DP_OUTBOX = "edi_dp_ob"
    EDI_AS2_SERVER = "edi_as2"
    EDI_AS2_PARTNER = "edi_as2_tp"
    EDI_AS2_PARTNERSHIP = "edi_as2_pship"
    EDI_SFTP_PARTNER = "edi_sftp"
    EDI_WEBHOOK = "edi_dp_wh"
    EDI_INBOUND_ROUTE = "edi_inb_rt"
    EDI_OUTBOUND_HEADER = "edi_outb_hdr"
    EDI_OUTBOUND_ROUTE = "edi_outb_rt"
    EDI_MESSAGE = "edi_msg"
    EDI_JSON = "edi_json"
    EDI_API_GATEWAY = "edi_api_gw"
    EDI_TRACE_EVENT = "edi_trace_evt"
    EDI_ACK = "edi_ack"


__all__ = [
    "EdiConstants",
    "EdiIdPrefix",
]
