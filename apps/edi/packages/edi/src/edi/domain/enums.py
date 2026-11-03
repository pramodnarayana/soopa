"""EDI Domain Enumerations."""

from enum import StrEnum


class EdiEventType(StrEnum):
    """Event types for EDI provisioning and lifecycle events across all subdomains."""

    # AS2 Trading Partner
    edi_as2_partner_created = "edi.as2_partner.created"
    edi_as2_partner_updated = "edi.as2_partner.updated"
    edi_as2_partner_deleted = "edi.as2_partner.deleted"

    # AS2 Partnership
    edi_as2_partnership_created = "edi.as2_partnership.created"
    edi_as2_partnership_updated = "edi.as2_partnership.updated"
    edi_as2_partnership_deleted = "edi.as2_partnership.deleted"

    # SFTP Partner
    edi_sftp_partner_created = "edi.sftp_partner.created"
    edi_sftp_partner_updated = "edi.sftp_partner.updated"
    edi_sftp_partner_deleted = "edi.sftp_partner.deleted"

    # Inbound Route
    edi_inbound_route_created = "edi.inbound_route.created"
    edi_inbound_route_updated = "edi.inbound_route.updated"
    edi_inbound_route_deleted = "edi.inbound_route.deleted"

    # Outbound Route
    edi_outbound_route_created = "edi.outbound_route.created"
    edi_outbound_route_updated = "edi.outbound_route.updated"
    edi_outbound_route_deleted = "edi.outbound_route.deleted"

    # Outbound EDI Header
    edi_header_created = "edi.header.created"
    edi_header_updated = "edi.header.updated"
    edi_header_deleted = "edi.header.deleted"


class EdiJobName(StrEnum):
    """Canonical event type names for EDI scheduled jobs."""

    EDI_CONTROL_PLANE_OUTBOX_SWEEPER = "EDI_CONTROL_PLANE_OUTBOX_SWEEPER"
    EDI_DATA_PLANE_OUTBOX_SWEEPER = "EDI_DATA_PLANE_OUTBOX_SWEEPER"
    EDI_CONTROL_PLANE_OUTBOX_CLEANUP = "EDI_CONTROL_PLANE_OUTBOX_CLEANUP"
    EDI_DATA_PLANE_OUTBOX_CLEANUP = "EDI_DATA_PLANE_OUTBOX_CLEANUP"
    EDI_DATA_RETENTION_CLEANUP = "EDI_DATA_RETENTION_CLEANUP"


class EdiOutboxSource(StrEnum):
    """Source tag for EDI outbox events."""

    EDI_DATA_PLANE = "edi_data_plane"
    EDI_CONTROL_PLANE = "edi_control_plane"


class EdiTraceEventType(StrEnum):
    """Canonical event types for EDI immutable audit ledger trace events."""

    RECEIVED = "RECEIVED"
    TRANSFORMATION_SUCCESSFUL = "TRANSFORMATION_SUCCESSFUL"
    TRANSFORMATION_FAILED = "TRANSFORMATION_FAILED"
    DELIVERY_SUCCESSFUL = "DELIVERY_SUCCESSFUL"
    DELIVERY_ATTEMPT_FAILED = "DELIVERY_ATTEMPT_FAILED"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    REPLAY_TRIGGERED = "REPLAY_TRIGGERED"
    REPLAY_TRANSFORM = "REPLAY_TRANSFORM"
    REPLAY_DELIVER = "REPLAY_DELIVER"
    MODIFY_AND_REPLAY_TRANSFORM = "MODIFY_AND_REPLAY_TRANSFORM"
    MODIFY_AND_REPLAY_DELIVER = "MODIFY_AND_REPLAY_DELIVER"
    CREATED_FROM_MODIFICATION = "CREATED_FROM_MODIFICATION"
    MODIFIED_AND_REPLAYED = "MODIFIED_AND_REPLAYED"


__all__ = [
    "EdiEventType",
    "EdiJobName",
    "EdiOutboxSource",
    "EdiTraceEventType",
]
