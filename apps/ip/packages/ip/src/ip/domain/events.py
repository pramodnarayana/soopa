"""Domain events for the Integration Platform bounded context."""

from dataclasses import dataclass

from seedwork.events import DomainEvent


@dataclass(frozen=True)
class ConnectionCreatedEvent(DomainEvent):
    connection_id: str
    tenant_id: str
    app_id: str
    connection_name: str
    auth_type: str

    @property
    def event_name(self) -> str:
        return "ip.connection.created"

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class ConnectionActivatedEvent(DomainEvent):
    connection_id: str
    tenant_id: str
    app_id: str

    @property
    def event_name(self) -> str:
        return "ip.connection.activated"

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class ConnectionDeactivatedEvent(DomainEvent):
    connection_id: str
    tenant_id: str
    app_id: str

    @property
    def event_name(self) -> str:
        return "ip.connection.deactivated"

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class ConnectionRelinkedEvent(DomainEvent):
    connection_id: str
    tenant_id: str
    app_id: str
    relinked_at: str

    @property
    def event_name(self) -> str:
        return "ip.connection.relinked"

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class ConnectionErrorRecordedEvent(DomainEvent):
    connection_id: str
    tenant_id: str
    error_code: str
    error_message: str

    @property
    def event_name(self) -> str:
        return "ip.connection.error_recorded"

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id
