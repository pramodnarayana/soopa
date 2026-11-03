"""Domain enums for the centralized Soopa platform trace capability."""

from __future__ import annotations

from enum import StrEnum


class TraceStatus(StrEnum):
    """Generic lifecycle status of a distributed trace across bounded contexts."""

    PENDING = "PENDING"
    STARTED = "STARTED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class TraceEventType(StrEnum):
    """Generic canonical event types for platform-wide immutable audit ledger trace events."""

    RECEIVED = "RECEIVED"
    STARTED = "STARTED"
    PROCESSING_SUCCESSFUL = "PROCESSING_SUCCESSFUL"
    PROCESSING_FAILED = "PROCESSING_FAILED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REPLAY_TRIGGERED = "REPLAY_TRIGGERED"


__all__ = ["TraceEventType", "TraceStatus"]
