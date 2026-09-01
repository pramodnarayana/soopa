from dataclasses import dataclass
from datetime import datetime

from seedwork.models import AggregateRoot


@dataclass(kw_only=True)
class WebhookDomainModel(AggregateRoot):
    id: str
    tenant_id: str
    name: str
    url: str
    active: bool
    created_at: datetime
    updated_at: datetime
    auth_header_vault_ref: str | None = None
