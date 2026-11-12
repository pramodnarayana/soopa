"""Pydantic HTTP request and response DTOs for subscribed ConnectionEntity endpoints."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ConnectionEntitySyncModeHttp(StrEnum):
    """HTTP wire enumeration for connection entity synchronization mode."""

    FULL_REFRESH = "FULL_REFRESH"
    INCREMENTAL = "INCREMENTAL"


class ConnectionEntityScheduleHttp(StrEnum):
    """HTTP wire enumeration for connection entity sync cadence."""

    MANUAL = "manual"
    EVERY_5M = "5m"
    EVERY_15M = "15m"
    HOURLY = "1h"
    EVERY_6H = "6h"
    DAILY = "24h"


class ConnectionEntitySyncFromHttp(StrEnum):
    """HTTP wire enumeration for connection entity historical lookback boundary."""

    ALL = "all"
    LAST_24H = "24h"
    LAST_7D = "7d"
    LAST_30D = "30d"
    LAST_90D = "90d"
    CUSTOM = "custom"


class ConnectionEntityFieldHttpDTO(BaseModel):
    """HTTP schema DTO representing a single field on a subscribed connection entity."""

    name: str = Field(..., min_length=1, max_length=128)
    data_type: str = Field(..., min_length=1, max_length=64)
    nullable: bool = True
    description: str | None = None


class AddConnectionEntityHttpRequest(BaseModel):
    """HTTP request DTO to subscribe an entity on a connection."""

    stream_name: str = Field(..., min_length=1, max_length=128)
    sync_mode: ConnectionEntitySyncModeHttp = ConnectionEntitySyncModeHttp.INCREMENTAL
    schedule: ConnectionEntityScheduleHttp = ConnectionEntityScheduleHttp.MANUAL
    sync_from: ConnectionEntitySyncFromHttp = ConnectionEntitySyncFromHttp.ALL
    sync_from_at: datetime | None = None
    is_enabled: bool = True
    primary_key: list[str] = Field(default_factory=list)
    fields: list[ConnectionEntityFieldHttpDTO] = Field(default_factory=list)
    cursor_field: str | None = Field(default=None, max_length=128)


class UpdateConnectionEntityHttpRequest(BaseModel):
    """HTTP request DTO to update sync configuration on a subscribed connection entity."""

    sync_mode: ConnectionEntitySyncModeHttp | None = None
    schedule: ConnectionEntityScheduleHttp | None = None
    sync_from: ConnectionEntitySyncFromHttp | None = None
    sync_from_at: datetime | None = None
    is_enabled: bool | None = None


class ConnectionEntityHttpResponse(BaseModel):
    """HTTP response DTO representing a subscribed ConnectionEntity."""

    entity_id: str
    tenant_id: str
    connection_id: str
    stream_name: str
    sync_mode: str
    schedule: str
    sync_from: str
    sync_from_at: datetime | None = None
    is_enabled: bool
    primary_key: list[str]
    fields: list[ConnectionEntityFieldHttpDTO]
    cursor_field: str | None = None
    cursor_value: str | None = None
    records_synced_count: int
    last_synced_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


__all__ = [
    "AddConnectionEntityHttpRequest",
    "ConnectionEntityFieldHttpDTO",
    "ConnectionEntityHttpResponse",
    "ConnectionEntityScheduleHttp",
    "ConnectionEntitySyncFromHttp",
    "ConnectionEntitySyncModeHttp",
    "UpdateConnectionEntityHttpRequest",
]
