"""Pydantic HTTP request and response DTOs for Connection Operational Policies."""

from __future__ import annotations

from pydantic import BaseModel, Field
from seedwork.domain.types import JsonDict


class UpsertConnectionPolicyHttpRequest(BaseModel):
    """HTTP request payload to configure or update operational policies for a Connection."""

    policy_id: str | None = None
    max_query_window_days: int | None = Field(default=None, ge=1)
    max_query_window_hours: int | None = Field(default=None, ge=1)
    min_query_window_minutes: int | None = Field(default=None, ge=1)
    max_entities_per_call: int | None = Field(default=None, ge=1)
    max_records_per_batch: int | None = Field(default=None, ge=1)
    max_concurrency: int | None = Field(default=None, ge=1)
    rate_limit_rpm: int | None = Field(default=None, ge=1)
    cooldown_seconds_between_calls: float | None = Field(default=None, ge=0.0)
    supports_wildcard_queries: bool | None = None
    blackout_cron_schedule: str | None = None
    blackout_duration_minutes: int | None = Field(default=None, ge=0)
    vendor_quirks: JsonDict | None = None
    is_enabled: bool | None = None


class ConnectionPolicyHttpResponse(BaseModel):
    """HTTP response payload representing an operational ConnectionPolicy."""

    id: str
    tenant_id: str
    connection_id: str
    max_query_window_days: int
    max_query_window_hours: int | None
    min_query_window_minutes: int
    max_entities_per_call: int
    max_records_per_batch: int
    max_concurrency: int
    rate_limit_rpm: int
    cooldown_seconds_between_calls: float
    supports_wildcard_queries: bool
    blackout_cron_schedule: str | None
    blackout_duration_minutes: int
    vendor_quirks: JsonDict = Field(default_factory=dict)
    is_enabled: bool
    created_at: str
    updated_at: str


__all__ = [
    "ConnectionPolicyHttpResponse",
    "UpsertConnectionPolicyHttpRequest",
]
