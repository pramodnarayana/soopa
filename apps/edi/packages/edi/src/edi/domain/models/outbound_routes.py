from dataclasses import dataclass
from datetime import datetime

from seedwork.models import AggregateRoot

from edi.domain.enums import EdiConnectionType, EdiDirection


@dataclass(kw_only=True)
class OutboundRouteDomainModel(AggregateRoot):
    ID_PREFIX = "edi_ob_rt"

    id: str
    tenant_id: str
    trading_partner_id: str | None = None
    name: str | None = None
    active: bool
    created_at: datetime
    updated_at: datetime
    connection_type: EdiConnectionType | None = None
    as2_partner_id: str | None = None
    sftp_partner_id: str | None = None
    direction: EdiDirection = EdiDirection.OUTBOUND
    destination_name: str | None = None
