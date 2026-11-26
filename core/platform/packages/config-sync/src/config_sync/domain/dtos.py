"""Pure immutable Domain DTOs for Control-to-Data-Plane Dynamic Watch synchronization."""

from __future__ import annotations

from dataclasses import dataclass

from seedwork.domain.types import JsonDict

from config_sync.domain.enums import ConfigChangeAction, ConfigSyncErrorCode


@dataclass(frozen=True, order=True)
class ConfigCursor:
    """Mathematically linearizable PostgreSQL MVCC total-order cursor `(txid, version)`.

    Ordering by `(txid, version)` strictly behind `pg_snapshot_xmin(pg_current_snapshot())`
    prevents sequence-vs-txid interleaving loss when an earlier transaction `T1 (txid=500)`
    acquires a higher `version=102` and commits before `T2 (txid=501, version=101)`.
    """

    txid: int
    version: int

    def encode(self) -> str:
        return f"{self.txid}:{self.version}"

    @property
    def is_zero(self) -> bool:
        return self.txid <= 0 and self.version <= 0

    @classmethod
    def zero(cls) -> ConfigCursor:
        return cls(txid=0, version=0)

    @classmethod
    def parse(cls, raw: str) -> ConfigCursor | None:
        parts = raw.strip().split(":")
        if len(parts) != 2:
            return None
        try:
            txid = int(parts[0])
            version = int(parts[1])
        except ValueError:
            return None
        if txid < 0 or version < 0:
            return None
        return cls(txid=txid, version=version)


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
    """Monotonically ordered incremental mutation streamed over Dynamic Watch."""

    event_id: str
    app_id: str
    tenant_id: str
    entity_type: str
    entity_id: str
    action: ConfigChangeAction
    version: int
    checksum: str
    payload: JsonDict
    txid: int = 0

    @property
    def cursor(self) -> ConfigCursor:
        return ConfigCursor(txid=self.txid, version=self.version)


@dataclass(frozen=True)
class ConfigSnapshot:
    """Authoritative full tenant catalog snapshot for cold-start and ring-buffer-evicted clients."""

    app_id: str
    tenant_id: str
    version: int
    entities: tuple[ConfigEntityRecord, ...]
    checksum: str
    txid: int = 0

    @property
    def cursor(self) -> ConfigCursor:
        return ConfigCursor(txid=self.txid, version=self.version)


@dataclass(frozen=True)
class ConfigWatchHeartbeat:
    """Periodic liveness frame enabling Data Plane disconnect detection."""

    app_id: str
    tenant_id: str
    latest_version: int
    timestamp: str
    latest_txid: int = 0

    @property
    def latest_cursor(self) -> ConfigCursor:
        return ConfigCursor(txid=self.latest_txid, version=self.latest_version)


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
    frame_id: str | None = None


@dataclass(frozen=True)
class ChangelogVisibilityWatermark:
    """Snapshot of linearizable (`txid < pg_snapshot_xmin`) vs raw changelog head cursors."""

    safe_cursor: ConfigCursor
    raw_max_cursor: ConfigCursor

    @property
    def safe_version(self) -> int:
        return self.safe_cursor.version

    @property
    def raw_max_version(self) -> int:
        return self.raw_max_cursor.version

    @property
    def is_lagged(self) -> bool:
        return self.raw_max_cursor > self.safe_cursor

    @property
    def lagged_txids(self) -> int:
        return max(0, self.raw_max_cursor.txid - self.safe_cursor.txid)


__all__ = [
    "ChangelogVisibilityWatermark",
    "ConfigCursor",
    "ConfigDeltaEvent",
    "ConfigEntityRecord",
    "ConfigSnapshot",
    "ConfigSyncError",
    "ConfigWatchFrame",
    "ConfigWatchHeartbeat",
]
