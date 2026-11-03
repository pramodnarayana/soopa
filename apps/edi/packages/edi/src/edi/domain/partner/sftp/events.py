"""SFTP Partner Domain Events."""

from dataclasses import dataclass
from enum import StrEnum

from seedwork.events import DomainEvent


class SftpPartnerEventType(StrEnum):
    """Event types for SFTP partner lifecycle."""

    edi_sftp_partner_created = "edi.sftp_partner.created"
    edi_sftp_partner_updated = "edi.sftp_partner.updated"
    edi_sftp_partner_deleted = "edi.sftp_partner.deleted"


@dataclass(frozen=True)
class SftpPartnerCreatedEvent(DomainEvent):
    tenant_id: str
    partner_id: str

    @property
    def event_name(self) -> str:
        return SftpPartnerEventType.edi_sftp_partner_created.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class SftpPartnerUpdatedEvent(DomainEvent):
    tenant_id: str
    partner_id: str

    @property
    def event_name(self) -> str:
        return SftpPartnerEventType.edi_sftp_partner_updated.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class SftpPartnerDeletedEvent(DomainEvent):
    tenant_id: str
    partner_id: str

    @property
    def event_name(self) -> str:
        return SftpPartnerEventType.edi_sftp_partner_deleted.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id
