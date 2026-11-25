"""Strongly-typed enums for the Universal Dynamic Watch Config Sync protocol."""

from __future__ import annotations

from enum import StrEnum


class ConfigChangeAction(StrEnum):
    """Atomic mutation operations streamed over Dynamic Watch."""

    UPSERT = "UPSERT"
    DELETE = "DELETE"


class ConfigWatchEventType(StrEnum):
    """Canonical Server-Sent Events (SSE) frame types for the Dynamic Watch wire protocol."""

    SNAPSHOT_START = "snapshot_start"
    SNAPSHOT_CHUNK = "snapshot_chunk"
    SNAPSHOT_END = "snapshot_end"
    DELTA = "delta"
    HEARTBEAT = "heartbeat"


class ConfigSyncChannel(StrEnum):
    """PostgreSQL LISTEN/NOTIFY channel identifier for multi-replica Dynamic Watch fan-out."""

    CONFIG_CHANGELOG_NOTIFY = "config_sync_changelog"


class ConfigSyncJobName(StrEnum):
    """Canonical scheduled maintenance job names for the Config Sync subsystem."""

    CONFIG_CHANGELOG_CLEANUP = "config_changelog_cleanup"


class ConfigSyncErrorCode(StrEnum):
    """First-class structured error codes for Dynamic Watch operations."""

    UNKNOWN_APP = "UNKNOWN_APP"
    CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"
    STREAM_DISCONNECTED = "STREAM_DISCONNECTED"
    UNAUTHORIZED = "UNAUTHORIZED"
    UNCONFIGURED_AUTH = "UNCONFIGURED_AUTH"
    INVALID_FRAME = "INVALID_FRAME"


__all__ = [
    "ConfigChangeAction",
    "ConfigSyncChannel",
    "ConfigSyncErrorCode",
    "ConfigSyncJobName",
    "ConfigWatchEventType",
]
