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
    status: str | None = None

    @property
    def event_name(self) -> str:
        return PipelineEventType.TRANSFORM_EVENT.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class TransformCompleted(DomainEvent):
    """
    Domain event emitted by the EdiMessage aggregate when an inbound EDI
    transform pipeline has successfully completed. The repository drains
    this event into the outbox within the same transaction.
    """

    trace_id: str
    tenant_id: str
    direction: str
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    transaction_type: str | None = None

    @property
    def event_name(self) -> str:
        return PipelineEventType.TRANSFORM_COMPLETED.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class TransactionReplayRequestedEvent(DomainEvent):
    trace_id: str
    tenant_id: str
    tier: str

    @property
    def event_name(self) -> str:
        return "edi.transaction.replay_requested"

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id
