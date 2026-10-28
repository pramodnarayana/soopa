"""Pydantic HTTP request and response DTOs for SyncRuns and StreamState checkpoints."""

from __future__ import annotations

from datetime import datetime

from ip.engine.domain.enums import SyncRunKind
from pydantic import BaseModel, Field


class TriggerSyncRunHttpRequest(BaseModel):
    """HTTP request DTO to queue an asynchronous pull synchronization run."""

    stream_name: str = Field(..., min_length=1)
    forced_kind: SyncRunKind | None = None
    correlation_id: str | None = None


class SyncRunHttpResponse(BaseModel):
    """HTTP response DTO representing a pull synchronization run."""

    run_id: str
    tenant_id: str
    connection_id: str
    stream_name: str
    kind: str
    generation_id: int
    status: str
    start_checkpoint: str | None = None
    end_checkpoint: str | None = None
    pages_count: int
    records_count: int
    bytes_count: int
    retry_count: int
    error_code: str | None = None
    error_message: str | None = None
    trace_id: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class StreamStateHttpResponse(BaseModel):
    """HTTP response DTO representing an incremental stream state checkpoint."""

    state_id: str
    tenant_id: str
    connection_id: str
    stream_name: str
    cursor_field: str | None = None
    cursor_value: str | None = None
    records_synced_count: int
    last_synced_at: datetime


__all__ = [
    "StreamStateHttpResponse",
    "SyncRunHttpResponse",
    "TriggerSyncRunHttpRequest",
]
