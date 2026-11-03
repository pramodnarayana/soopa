"""Routing Domain Enumerations."""

from enum import StrEnum


class EdiDirection(StrEnum):
    """The direction of an EDI message."""

    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


Direction = EdiDirection


class ConnectionType(StrEnum):
    """Logical connection type for domain routing and provisioning records."""

    AS2 = "AS2"
    SFTP = "SFTP"
    WEBHOOK = "WEBHOOK"
    API = "API"
    UNKNOWN = "UNKNOWN"


EdiConnectionType = ConnectionType


class ProcessingMode(StrEnum):
    """How an inbound route should handle EDI payload transformation."""

    TRANSFORM = "TRANSFORM"
    PASSTHROUGH = "PASSTHROUGH"


class RouteStatus(StrEnum):
    """Lifecycle status of a route."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class OutboundRouteType(StrEnum):
    """Destination type for outbound routes."""

    AS2 = "AS2"
    SFTP = "SFTP"
    WEBHOOK = "WEBHOOK"


class WebhookEventType(StrEnum):
    """Domain events for webhook configuration lifecycle."""

    webhook_created = "webhook.created"
    webhook_updated = "webhook.updated"
    webhook_deleted = "webhook.deleted"
