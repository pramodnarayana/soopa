"""Pydantic HTTP request and response DTOs for Stitch DAG Task Runtime Configurations."""

from __future__ import annotations

from pydantic import BaseModel, Field


class UpsertStitchTaskConfigHttpRequest(BaseModel):
    """HTTP request payload to configure or update task runtime execution policies."""

    config_id: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1)
    heartbeat_interval_seconds: int | None = Field(default=None, ge=1)
    max_attempts: int | None = Field(default=None, ge=1)
    initial_delay_seconds: float | None = Field(default=None, ge=0.0)
    backoff_multiplier: float | None = Field(default=None, ge=1.0)
    max_delay_seconds: float | None = Field(default=None, ge=0.0)
    queue_name: str | None = Field(default=None, max_length=64)
    max_in_flight_tasks: int | None = Field(default=None, ge=1)
    failure_disposition: str | None = Field(default=None, max_length=32)
    quarantine_stream_name: str | None = Field(default=None, max_length=128)


class StitchTaskConfigHttpResponse(BaseModel):
    """HTTP response payload representing a StitchTaskConfig."""

    id: str
    tenant_id: str
    stitch_id: str
    node_key: str
    timeout_seconds: int
    heartbeat_interval_seconds: int
    max_attempts: int
    initial_delay_seconds: float
    backoff_multiplier: float
    max_delay_seconds: float
    queue_name: str
    max_in_flight_tasks: int
    failure_disposition: str
    quarantine_stream_name: str | None
    created_at: str
    updated_at: str


__all__ = [
    "StitchTaskConfigHttpResponse",
    "UpsertStitchTaskConfigHttpRequest",
]
