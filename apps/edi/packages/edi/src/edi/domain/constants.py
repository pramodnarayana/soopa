"""
EDI Domain Constants
====================

Non-enumeration constants for the EDI bounded context.
All StrEnum definitions live in ``edi.domain.enums``.
"""

# ── ID prefixes ──────────────────────────────────────────────────────────────
# Kept here because EdiIdPrefix drives repository ID generation and is referenced
# in many adapters — it is not a business-status enum, it is a naming convention.
from enum import StrEnum

from edi.domain.enums import (
    EdiEventType,
    MessageQueueName,
    NotificationEventType,
    PipelineEventType,
    UcpEventType,
    WebhookEventType,
)


class EdiIdPrefix(StrEnum):
    CP_OUTBOX = "edi_cp_ob"
    DP_OUTBOX = "edi_dp_ob"
    AS2_SERVER = "edi_as2"
    AS2_PARTNER = "edi_as2p"
    SFTP_PARTNER = "edi_sftp"
    WEBHOOK = "edi_dp_wh"
    INBOUND_ROUTE = "edi_inbrt"
    OUTBOUND_HEADER = "edi_outhdr"
    OUTBOUND_ROUTE = "edi_outrt"
    EDI_MESSAGE = "edi_msg"
    EDI_JSON = "edi_json"
    API_GATEWAY = "edi_apigw"


EDI_MESSAGE_ID_PREFIX = EdiIdPrefix.EDI_MESSAGE.value

# ── Pipeline event → queue routing map ──────────────────────────────────────
PIPELINE_EVENT_ROUTING_MAP: dict[str, str] = {
    PipelineEventType.TRANSFORM_EVENT: MessageQueueName.TRANSFORM_QUEUE,
    PipelineEventType.COMPUTE_TRANSFORM_EVENT: MessageQueueName.TRANSFORM_QUEUE,
    PipelineEventType.TRANSFORM_COMPLETED: MessageQueueName.LIFECYCLE_QUEUE,
    PipelineEventType.DELIVER_EVENT: MessageQueueName.DELIVER_QUEUE,
    PipelineEventType.DELIVERY_COMPLETED: MessageQueueName.LIFECYCLE_QUEUE,
    NotificationEventType.NOTIFICATION_TRIGGERED: MessageQueueName.PRIORITY_NOTIFICATIONS_QUEUE,
}

# ── Aggregated provisioning event set ────────────────────────────────────────
ProvisioningEventType = EdiEventType | WebhookEventType | UcpEventType

ALL_PROVISIONING_EVENT_TYPES = (
    [e.value for e in EdiEventType]
    + [e.value for e in WebhookEventType]
    + [e.value for e in UcpEventType]
)
