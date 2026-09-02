from dataclasses import dataclass
from datetime import datetime

from seedwork.models import AggregateRoot


@dataclass(kw_only=True)
class SFTPPartnerDomainModel(AggregateRoot):
    ID_PREFIX = "sftp"

    id: str
    tenant_id: str
    name: str
    host: str
    port: int
    username: str
    active: bool
    created_at: datetime
    updated_at: datetime
    host_key: str | None = None
    inbound_remote_path: str | None = None
    outbound_remote_path: str | None = None
    password_encrypted: str | None = None
    credentials_vault_ref: str | None = None
    deleted_at: datetime | None = None
