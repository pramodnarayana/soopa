from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InboundRouteDTO:
    """Resolved routing configuration for an inbound EDI message."""

    trading_partner_id: str | None = None
    webhook_id: str | None = None
    as2_partner_id: str | None = None
    sftp_partner_id: str | None = None
    processing_mode: str | None = None


@dataclass(frozen=True)
class OutboundRouteDTO:
    """Maps to the OutboundRoute table."""

    route_id: str = ""
    trading_partner_id: str | None = None
    as2_partner_id: str | None = None
    sftp_partner_id: str | None = None
    webhook_id: str | None = None
    protocol: str | None = None


@dataclass(frozen=True)
class OutboundEdiHeaderDTO:
    """Maps to the OutboundEdiHeader table."""

    isa_sender_id: str | None = None
    isa_receiver_id: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    default_standard: str | None = None
    default_version: str | None = None
    isa_sender_qualifier: str | None = None
    isa_receiver_qualifier: str | None = None
    isa_control_version: str | None = None
    isa_usage_indicator: str | None = None
    gs_version: str | None = None
    segment_terminator: str | None = None
    element_separator: str | None = None
    subelement_separator: str | None = None
