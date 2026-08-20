from enum import StrEnum

from pydantic import BaseModel


class UcpEventType(StrEnum):
    app_subscribed = "app.subscribed"
    app_unsubscribed = "app.unsubscribed"
    api_key_created = "api_key.created"


class WebhookEventType(StrEnum):
    webhook_created = "webhook.created"
    webhook_updated = "webhook.updated"
    webhook_deleted = "webhook.deleted"


class EdiEventType(StrEnum):
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


class PipelineEventType(StrEnum):
    TRANSFORM_EVENT = "TRANSFORM_EVENT"
    COMPUTE_TRANSFORM_EVENT = "COMPUTE_TRANSFORM_EVENT"
    TRANSFORM_COMPLETED = "TRANSFORM_COMPLETED"
    DELIVER_EVENT = "DELIVER_EVENT"
    DELIVERY_COMPLETED = "DELIVERY_COMPLETED"


class NotificationEventType(StrEnum):
    NOTIFICATION_TRIGGERED = "notification.triggered"


ProvisioningEventType = EdiEventType | WebhookEventType | UcpEventType

ALL_PROVISIONING_EVENT_TYPES = (
    [e.value for e in EdiEventType]
    + [e.value for e in WebhookEventType]
    + [e.value for e in UcpEventType]
)


class ProvisioningEvent(BaseModel):
    tenant_id: str
    event_type: ProvisioningEventType
    resource_id: str | None = None


class MessageQueueName(StrEnum):
    TRANSFORM_QUEUE = "edi-transform"
    LIFECYCLE_QUEUE = "edi-lifecycle"
    DELIVER_QUEUE = "edi-deliver"
    PROVISIONING_QUEUE = "edi-config-sync"
    CDC_DLQ_QUEUE = "edi-cdc-dlq"
    PRIORITY_NOTIFICATIONS_QUEUE = "edi-priority-notifications"


PIPELINE_EVENT_ROUTING_MAP: dict[str, str] = {
    PipelineEventType.TRANSFORM_EVENT: MessageQueueName.TRANSFORM_QUEUE,
    PipelineEventType.COMPUTE_TRANSFORM_EVENT: MessageQueueName.TRANSFORM_QUEUE,
    PipelineEventType.TRANSFORM_COMPLETED: MessageQueueName.LIFECYCLE_QUEUE,
    PipelineEventType.DELIVER_EVENT: MessageQueueName.DELIVER_QUEUE,
    PipelineEventType.DELIVERY_COMPLETED: MessageQueueName.LIFECYCLE_QUEUE,
    NotificationEventType.NOTIFICATION_TRIGGERED: MessageQueueName.PRIORITY_NOTIFICATIONS_QUEUE,
}
