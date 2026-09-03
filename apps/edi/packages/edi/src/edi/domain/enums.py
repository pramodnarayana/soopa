"""
EDI Domain Enumerations
=======================

Single source of truth for all business-level enumeration types in the EDI
bounded context. Every status, direction, connection type, and event category
that carries semantic meaning MUST be defined here as a StrEnum.

Rules:
- No raw string literals in application or domain code — always use these enums.
- Do NOT add enums that belong to infrastructure (e.g. SQLAlchemy column choices
  that have no business meaning). Those stay in the adapter layer.
"""

from enum import StrEnum


class EdiDirection(StrEnum):
    """The flow direction of an EDI transmission relative to this system."""

    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class MessageStatus(StrEnum):
    """Lifecycle status of an EDI message or JSON record."""

    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    PENDING = "PENDING"
    PARSED = "PARSED"
    TRANSFORMED = "TRANSFORMED"
    PENDING_DELIVERY = "PENDING_DELIVERY"
    PROCESSING = "PROCESSING"
    DELIVERED = "DELIVERED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    ERROR = "ERROR"


class AuditLogStatus(StrEnum):
    """Status values for the AuditLog step-level tracing model."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    SKIPPED = "SKIPPED"


class EdiConnectionType(StrEnum):
    """The transport protocol used to exchange an EDI message."""

    AS2 = "AS2"
    API = "API"
    SFTP = "SFTP"


class EdiStandard(StrEnum):
    """The EDI format standard of the message payload."""

    X12 = "x12"
    EDIFACT = "edifact"


class EdiTransactionType(StrEnum):
    """Well-known X12 transaction set identifiers plus the generic envelope type."""

    ENVELOPE = "envelope"
    X12_204 = "204"
    X12_210 = "210"
    X12_214 = "214"
    X12_810 = "810"
    X12_850 = "850"
    X12_990 = "990"
    X12_997 = "997"


class PartnerStatus(StrEnum):
    """Provisioning lifecycle of a trading partner (AS2 or SFTP)."""

    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ConnectionType(StrEnum):
    """Logical connection type for domain routing and provisioning records."""

    AS2 = "AS2"
    SFTP = "SFTP"
    WEBHOOK = "WEBHOOK"
    API = "API"
    UNKNOWN = "UNKNOWN"


class ProcessingMode(StrEnum):
    """How an inbound route should handle EDI payload transformation."""

    TRANSFORM = "TRANSFORM"
    PASSTHROUGH = "PASSTHROUGH"


class EdiEventType(StrEnum):
    """Domain events emitted during EDI provisioning lifecycle operations."""

    edi_as2_partner_created = "edi.as2_partner.created"
    edi_as2_partner_updated = "edi.as2_partner.updated"
    edi_as2_partner_deleted = "edi.as2_partner.deleted"
    edi_as2_partnership_created = "edi.as2_partnership.created"
    edi_as2_partnership_updated = "edi.as2_partnership.updated"
    edi_as2_partnership_deleted = "edi.as2_partnership.deleted"
    edi_sftp_partner_created = "edi.sftp_partner.created"
    edi_sftp_partner_updated = "edi.sftp_partner.updated"
    edi_sftp_partner_deleted = "edi.sftp_partner.deleted"
    edi_inbound_route_created = "edi.inbound_route.created"
    edi_inbound_route_updated = "edi.inbound_route.updated"
    edi_inbound_route_deleted = "edi.inbound_route.deleted"
    edi_outbound_route_created = "edi.outbound_route.created"
    edi_outbound_route_updated = "edi.outbound_route.updated"
    edi_outbound_route_deleted = "edi.outbound_route.deleted"
    edi_header_created = "edi.header.created"
    edi_header_updated = "edi.header.updated"
    edi_header_deleted = "edi.header.deleted"


class UcpEventType(StrEnum):
    """Domain events for UCP app subscription lifecycle."""

    app_subscribed = "app.subscribed"
    app_unsubscribed = "app.unsubscribed"
    api_key_created = "api_key.created"


class WebhookEventType(StrEnum):
    """Domain events for webhook configuration lifecycle."""

    webhook_created = "webhook.created"
    webhook_updated = "webhook.updated"
    webhook_deleted = "webhook.deleted"


class PipelineEventType(StrEnum):
    """Internal pipeline orchestration event types (SQS message type discriminators)."""

    TRANSFORM_EVENT = "TRANSFORM_EVENT"
    COMPUTE_TRANSFORM_EVENT = "COMPUTE_TRANSFORM_EVENT"
    TRANSFORM_COMPLETED = "TRANSFORM_COMPLETED"
    DELIVER_EVENT = "DELIVER_EVENT"
    DELIVERY_COMPLETED = "DELIVERY_COMPLETED"


class NotificationEventType(StrEnum):
    """Cross-bounded-context notification trigger event type."""

    NOTIFICATION_TRIGGERED = "notification.triggered"


class MessageQueueName(StrEnum):
    """Canonical SQS queue names for the EDI pipeline."""

    TRANSFORM_QUEUE = "edi-transform.fifo"
    LIFECYCLE_QUEUE = "edi-lifecycle.fifo"
    DELIVER_QUEUE = "edi-deliver.fifo"
    PROVISIONING_QUEUE = "edi-config-sync-queue.fifo"
    CDC_DLQ_QUEUE = "edi-cdc-dlq.fifo"
    PRIORITY_NOTIFICATIONS_QUEUE = "edi-priority-notifications.fifo"
    DATA_PLANE_JOBS_QUEUE = "edi-data-plane-jobs.fifo"
    CONTROL_PLANE_JOBS_QUEUE = "edi-control-plane-jobs.fifo"
