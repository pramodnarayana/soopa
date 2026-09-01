from dataclasses import dataclass
from datetime import datetime

from seedwork.models import AggregateRoot


@dataclass(kw_only=True)
class OutboundRouteDomainModel(AggregateRoot):
    ID_PREFIX = "out"

    id: str
    tenant_id: str
    trading_partner_id: str | None = None
    name: str | None = None
    active: bool
    created_at: datetime
    updated_at: datetime
    protocol: str | None = None
    as2_partner_id: str | None = None
    sftp_partner_id: str | None = None
    direction: str = "OUTBOUND"
    destination_name: str | None = None
