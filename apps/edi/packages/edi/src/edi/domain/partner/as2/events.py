"""AS2 Partner Domain Events."""

from dataclasses import dataclass
from enum import StrEnum

from seedwork.events import DomainEvent


class As2PartnerEventType(StrEnum):
    """Event types for AS2 partner and partnership lifecycle."""

    edi_as2_partner_created = "edi.as2_partner.created"
    edi_as2_partner_updated = "edi.as2_partner.updated"
    edi_as2_partner_deleted = "edi.as2_partner.deleted"
    edi_as2_partnership_created = "edi.as2_partnership.created"
    edi_as2_partnership_updated = "edi.as2_partnership.updated"
    edi_as2_partnership_deleted = "edi.as2_partnership.deleted"


@dataclass(frozen=True)
class As2PartnerCreatedEvent(DomainEvent):
    tenant_id: str
    partner_id: str

    @property
    def event_name(self) -> str:
        return As2PartnerEventType.edi_as2_partner_created.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class As2PartnerUpdatedEvent(DomainEvent):
    tenant_id: str
    partner_id: str

    @property
    def event_name(self) -> str:
        return As2PartnerEventType.edi_as2_partner_updated.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class As2PartnerDeletedEvent(DomainEvent):
    tenant_id: str
    partner_id: str

    @property
    def event_name(self) -> str:
        return As2PartnerEventType.edi_as2_partner_deleted.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class As2PartnershipCreatedEvent(DomainEvent):
    tenant_id: str
    partnership_id: str

    @property
    def event_name(self) -> str:
        return As2PartnerEventType.edi_as2_partnership_created.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class As2PartnershipUpdatedEvent(DomainEvent):
    tenant_id: str
    partnership_id: str

    @property
    def event_name(self) -> str:
        return As2PartnerEventType.edi_as2_partnership_updated.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class As2PartnershipDeletedEvent(DomainEvent):
    tenant_id: str
    partnership_id: str

    @property
    def event_name(self) -> str:
        return As2PartnerEventType.edi_as2_partnership_deleted.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id
