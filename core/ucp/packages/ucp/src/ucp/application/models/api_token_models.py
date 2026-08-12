from dataclasses import dataclass
from datetime import datetime


@dataclass
class CreateApiTokenCommand:
    name: str
    expires_at: datetime | None = None


@dataclass
class UpdateApiTokenCommand:
    name: str | None = None
    active: bool | None = None


@dataclass
class ApiTokenCreatedResult:
    id: str
    name: str
    client_id: str
    active: bool
    last_used_at: datetime | None
    expires_at: datetime | None
    created_at: datetime
    token: str
