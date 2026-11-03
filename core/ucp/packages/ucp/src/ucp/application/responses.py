"""Shared application read/command response DTOs for the UCP bounded context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ApiTokenCreatedResponse:
    """One-time response DTO returned when a tenant API token is created."""

    id: str
    name: str
    client_id: str
    active: bool
    last_used_at: datetime | None
    expires_at: datetime | None
    created_at: datetime
    token: str


__all__ = ["ApiTokenCreatedResponse"]
