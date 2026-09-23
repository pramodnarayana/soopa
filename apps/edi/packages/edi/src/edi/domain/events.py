"""
EDI Domain Events
=================

Dataclasses representing pure domain events emitted by the EDI bounded context.
"""

from dataclasses import dataclass

from seedwork.events import DomainEvent

from edi.domain.constants import ProvisioningEventType
from edi.domain.enums import PipelineEventType


@dataclass(frozen=True)
class ProvisioningEvent(DomainEvent):
    tenant_id: str
    event_type: ProvisioningEventType
    resource_id: str | None = None

    @property
    def event_name(self) -> str:
        return str(self.event_type)

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class TransformRequestedEvent(DomainEvent):
    trace_id: str
    tenant_id: str
    trading_partner_id: str | None = None
    sender_id: str | None = None
    receiver_id: str | None = None
    direction: str | None = None
    edi_message_id: str | None = None

    @property
    def event_name(self) -> str:
        return PipelineEventType.TRANSFORMATION_REQUESTED.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class TransformSuccessful(DomainEvent):
    """
    Domain event emitted when an EDI transform pipeline has successfully completed
    (both inbound and outbound). The repository drains this event into the outbox
    within the same transaction.
    """

    trace_id: str
    tenant_id: str
    direction: str
    isa_sender_id: str | None = None
    isa_receiver_id: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    transaction_type: str | None = None

    @property
    def event_name(self) -> str:
        return PipelineEventType.TRANSFORMATION_SUCCESSFUL.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class TransformFailed(DomainEvent):
    """
    Domain event emitted when an EDI transform pipeline has fatally failed.
    The repository drains this event into the outbox before re-raising the exception
    to NACK the message.
    """

    trace_id: str
    tenant_id: str
    direction: str
    failure_reason: str

    @property
    def event_name(self) -> str:
        return PipelineEventType.TRANSFORMATION_FAILED.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class DeliverRequestedEvent(DomainEvent):
    trace_id: str
    tenant_id: str
    trading_partner_id: str | None = None
    transaction_type: str | None = None
    direction: str | None = None

    @property
    def event_name(self) -> str:
        return PipelineEventType.DELIVERY_REQUESTED.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class DeliverySuccessful(DomainEvent):
    """
    Domain event emitted when an EDI message is successfully delivered.
    """

    trace_id: str
    tenant_id: str
    direction: str

    @property
    def event_name(self) -> str:
        return PipelineEventType.DELIVERY_SUCCESSFUL.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class DeliveryFailed(DomainEvent):
    """
    Domain event emitted when an EDI message delivery fatally fails.
    """

    trace_id: str
    tenant_id: str
    direction: str
    failure_reason: str

    @property
    def event_name(self) -> str:
        return PipelineEventType.DELIVERY_FAILED.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id
