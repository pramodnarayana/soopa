"""SFTP Domain Subdomain Package."""

from edi.domain.partner.sftp.events import (
    SftpPartnerCreatedEvent,
    SftpPartnerDeletedEvent,
    SftpPartnerEventType,
    SftpPartnerUpdatedEvent,
)
from edi.domain.partner.sftp.partner import SFTPPartner

__all__ = [
    "SFTPPartner",
    "SftpPartnerCreatedEvent",
    "SftpPartnerDeletedEvent",
    "SftpPartnerEventType",
    "SftpPartnerUpdatedEvent",
]
