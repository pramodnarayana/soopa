"""Domain events for the Connection aggregate."""

from dataclasses import dataclass

from seedwork.events import DomainEvent

from ip.engine.domain.enums import IpEventType


@dataclass(frozen=True)
class ConnectionCreatedEvent(DomainEvent):
    connection_id: str
    tenant_id: str
    app_id: str
    connection_name: str
    auth_type: str

    @property
    def event_name(self) -> str:
        return IpEventType.CONNECTION_CREATED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class ConnectionActivatedEvent(DomainEvent):
    connection_id: str
    tenant_id: str
    app_id: str

    @property
    def event_name(self) -> str:
        return IpEventType.CONNECTION_ACTIVATED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class ConnectionDeactivatedEvent(DomainEvent):
    connection_id: str
    tenant_id: str
    app_id: str

    @property
    def event_name(self) -> str:
        return IpEventType.CONNECTION_DEACTIVATED

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
        return IpEventType.CONNECTION_RELINKED

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
        return IpEventType.CONNECTION_ERROR_RECORDED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id
