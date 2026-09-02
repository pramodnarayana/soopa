from dataclasses import dataclass
from datetime import datetime

from seedwork.models import AggregateRoot

from edi.domain.models.base import ProcessingMode


@dataclass(kw_only=True)
class InboundRouteDomainModel(AggregateRoot):
    ID_PREFIX = "in"

    id: str
    tenant_id: str
    name: str | None = None
    isa_sender_id: str
    isa_receiver_id: str
    active: bool
    created_at: datetime
    updated_at: datetime
    trading_partner_id: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    transaction_type: str | None = None
    processing_mode: ProcessingMode | None = None
    webhook_id: str | None = None
    as2_partner_id: str | None = None
    sftp_partner_id: str | None = None
    direction: str = "INBOUND"
    destination_name: str | None = None
