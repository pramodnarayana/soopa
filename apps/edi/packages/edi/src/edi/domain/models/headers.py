from dataclasses import dataclass
from datetime import datetime

from seedwork.models import AggregateRoot


@dataclass(kw_only=True)
class OutboundEdiHeaderDomainModel(AggregateRoot):
    ID_PREFIX = "hdr"

    id: str
    tenant_id: str
    trading_partner_id: str
    isa_sender_id: str
    isa_receiver_id: str
    created_at: datetime
    updated_at: datetime
    name: str | None = None
    isa_sender_qualifier: str | None = None
    isa_receiver_qualifier: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    transaction_type: str | None = None
    default_standard: str | None = None
    default_version: str | None = None
    isa_control_version: str | None = None
    isa_usage_indicator: str | None = None
    gs_version: str | None = None
    segment_terminator: str | None = None
    element_separator: str | None = None
    subelement_separator: str | None = None
