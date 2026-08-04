from enum import StrEnum

from platform_schemas.edi_events import EdiEventType
from platform_schemas.ucp_events import UcpEventType
from platform_schemas.webhook_events import WebhookEventType
from pydantic import BaseModel


class PipelineEventType(StrEnum):
    TRANSFORM_EVENT = "TRANSFORM_EVENT"
    COMPUTE_TRANSFORM_EVENT = "COMPUTE_TRANSFORM_EVENT"
    TRANSFORM_COMPLETED = "TRANSFORM_COMPLETED"
    DELIVER_EVENT = "DELIVER_EVENT"
    DELIVERY_COMPLETED = "DELIVERY_COMPLETED"


# Legacy UCP events used by the worker for full sync
class LegacyUcpEventType(StrEnum):
    PROVISION_ALL_TENANTS = "tenant.provision_all"
    PROVISION_TENANT = "tenant.provision"


ProvisioningEventType = EdiEventType | WebhookEventType | UcpEventType | LegacyUcpEventType

ALL_PROVISIONING_EVENT_TYPES = (
    [e.value for e in EdiEventType]
    + [e.value for e in WebhookEventType]
    + [e.value for e in UcpEventType]
    + [e.value for e in LegacyUcpEventType]
)


class ProvisioningEvent(BaseModel):
    tenant_id: str
    event_type: ProvisioningEventType
    resource_id: str | None = None


class MessageQueueName(StrEnum):
    TRANSFORM_ORCHESTRATION_QUEUE = "TransformOrchestrationQueue"
    DELIVER_QUEUE = "DeliverQueue"
    PROVISIONING_QUEUE = "ProvisioningQueue"
    TRANSFORM_COMPUTE_QUEUE = "TransformComputeQueue"
    CDC_DLQ_QUEUE = "CDC-DLQ"


PIPELINE_EVENT_ROUTING_MAP: dict[str, str] = {
    PipelineEventType.TRANSFORM_EVENT: MessageQueueName.TRANSFORM_ORCHESTRATION_QUEUE,
    PipelineEventType.COMPUTE_TRANSFORM_EVENT: MessageQueueName.TRANSFORM_COMPUTE_QUEUE,
    PipelineEventType.TRANSFORM_COMPLETED: MessageQueueName.TRANSFORM_ORCHESTRATION_QUEUE,
    PipelineEventType.DELIVER_EVENT: MessageQueueName.DELIVER_QUEUE,
    PipelineEventType.DELIVERY_COMPLETED: MessageQueueName.TRANSFORM_ORCHESTRATION_QUEUE,
}
