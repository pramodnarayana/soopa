"""Routing Domain Events."""

from dataclasses import dataclass
from enum import StrEnum

from seedwork.events import DomainEvent


class InboundRouteEventType(StrEnum):
    """Event types for inbound route lifecycle."""

    edi_inbound_route_created = "edi.inbound_route.created"
    edi_inbound_route_updated = "edi.inbound_route.updated"
    edi_inbound_route_deleted = "edi.inbound_route.deleted"


class OutboundRouteEventType(StrEnum):
    """Event types for outbound route lifecycle."""

    edi_outbound_route_created = "edi.outbound_route.created"
    edi_outbound_route_updated = "edi.outbound_route.updated"
    edi_outbound_route_deleted = "edi.outbound_route.deleted"


class HeaderEventType(StrEnum):
    """Event types for EDI header lifecycle."""

    edi_header_created = "edi.header.created"
    edi_header_updated = "edi.header.updated"
    edi_header_deleted = "edi.header.deleted"


@dataclass(frozen=True)
class InboundRouteCreatedEvent(DomainEvent):
    tenant_id: str
    route_id: str

    @property
    def event_name(self) -> str:
        return InboundRouteEventType.edi_inbound_route_created.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class InboundRouteUpdatedEvent(DomainEvent):
    tenant_id: str
    route_id: str

    @property
    def event_name(self) -> str:
        return InboundRouteEventType.edi_inbound_route_updated.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class InboundRouteDeletedEvent(DomainEvent):
    tenant_id: str
    route_id: str

    @property
    def event_name(self) -> str:
        return InboundRouteEventType.edi_inbound_route_deleted.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class OutboundRouteCreatedEvent(DomainEvent):
    tenant_id: str
    route_id: str

    @property
    def event_name(self) -> str:
        return OutboundRouteEventType.edi_outbound_route_created.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class OutboundRouteUpdatedEvent(DomainEvent):
    tenant_id: str
    route_id: str

    @property
    def event_name(self) -> str:
        return OutboundRouteEventType.edi_outbound_route_updated.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class OutboundRouteDeletedEvent(DomainEvent):
    tenant_id: str
    route_id: str

    @property
    def event_name(self) -> str:
        return OutboundRouteEventType.edi_outbound_route_deleted.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class EdiHeaderCreatedEvent(DomainEvent):
    tenant_id: str
    header_id: str

    @property
    def event_name(self) -> str:
        return HeaderEventType.edi_header_created.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class EdiHeaderUpdatedEvent(DomainEvent):
    tenant_id: str
    header_id: str

    @property
    def event_name(self) -> str:
        return HeaderEventType.edi_header_updated.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class EdiHeaderDeletedEvent(DomainEvent):
    tenant_id: str
    header_id: str

    @property
    def event_name(self) -> str:
        return HeaderEventType.edi_header_deleted.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id
