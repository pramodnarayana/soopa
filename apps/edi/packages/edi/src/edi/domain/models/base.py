from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from seedwork.models import AggregateRoot

from edi.domain.enums import EdiDirection, MessageStatus

# Re-export canonical enums so existing callers of `from edi.domain.models.base import ...`
# keep working without changes during the transition.
Direction = EdiDirection
RecordStatus = MessageStatus


class PartnerStatus(StrEnum):
    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ConnectionType(StrEnum):
    AS2 = "AS2"
    SFTP = "SFTP"
    WEBHOOK = "WEBHOOK"
    API = "API"
    UNKNOWN = "UNKNOWN"


class ProcessingMode(StrEnum):
    TRANSFORM = "TRANSFORM"
    PASSTHROUGH = "PASSTHROUGH"


@dataclass(kw_only=True)
class EdiRecordBase(AggregateRoot):
    id: str
    tenant_id: str
    trace_id: str
    direction: EdiDirection
    status: MessageStatus
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if isinstance(self.id, UUID):
            self.id = str(self.id)
        if isinstance(self.tenant_id, UUID):
            self.tenant_id = str(self.tenant_id)
        if isinstance(self.trace_id, UUID):
            self.trace_id = str(self.trace_id)
