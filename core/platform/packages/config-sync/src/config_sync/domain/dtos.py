"""Pure immutable Domain DTOs for Control-to-Data-Plane Dynamic Watch synchronization."""

from __future__ import annotations

from dataclasses import dataclass

from seedwork.domain.types import JsonDict

from config_sync.domain.enums import ConfigChangeAction, ConfigSyncErrorCode


@dataclass(frozen=True)
class ConfigEntityRecord:
    """Single authoritative entity state included inside a baseline `ConfigSnapshot`."""

    entity_type: str
    entity_id: str
    tenant_id: str
    payload: JsonDict
    checksum: str


@dataclass(frozen=True)
class ConfigDeltaEvent:
    """Monotonically versioned incremental mutation streamed over Dynamic Watch."""

    event_id: str
    app_id: str
    tenant_id: str
    entity_type: str
    entity_id: str
    action: ConfigChangeAction
    version: int
    checksum: str
    payload: JsonDict


@dataclass(frozen=True)
class ConfigSnapshot:
    """Authoritative full tenant catalog snapshot for cold-start and ring-buffer-evicted clients."""

    app_id: str
    tenant_id: str
    version: int
    entities: tuple[ConfigEntityRecord, ...]
    checksum: str


@dataclass(frozen=True)
class ConfigWatchHeartbeat:
    """Periodic liveness frame enabling Data Plane disconnect detection."""

    app_id: str
    tenant_id: str
    latest_version: int
    timestamp: str


@dataclass(frozen=True)
class ConfigSyncError:
    """First-class structured error value returned by Dynamic Watch operations."""

    code: ConfigSyncErrorCode
    message: str


@dataclass(frozen=True)
class ConfigWatchFrame:
    """Typed SSE wire frame produced by `StreamConfigWatchUseCase`."""

    event: str
    data: JsonDict


__all__ = [
    "ConfigDeltaEvent",
    "ConfigEntityRecord",
    "ConfigSnapshot",
    "ConfigSyncError",
    "ConfigWatchFrame",
    "ConfigWatchHeartbeat",
]
