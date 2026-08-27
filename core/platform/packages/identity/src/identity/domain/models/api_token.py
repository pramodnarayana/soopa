from dataclasses import dataclass
from datetime import datetime


@dataclass
class ApiTokenDomainModel:
    id: str
    tenant_id: str
    name: str
    client_id: str
    secret_hash: str
    last_used_at: datetime | None
    expires_at: datetime | None
    active: bool
    created_at: datetime
    updated_at: datetime
