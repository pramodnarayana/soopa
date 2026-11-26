"""Pure in-memory deterministic fakes for testing Dynamic Watch without external infrastructure."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from seedwork.domain.exceptions import Result
from seedwork.domain.types import JsonDict
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id

from config_sync.domain.checksum import compute_payload_checksum, compute_snapshot_checksum
from config_sync.domain.dtos import (
    ChangelogVisibilityWatermark,
    ConfigCursor,
    ConfigDeltaEvent,
    ConfigEntityRecord,
    ConfigSnapshot,
    ConfigSyncError,
)
from config_sync.domain.enums import ConfigChangeAction, ConfigSyncErrorCode
from config_sync.ports.config_catalog_provider_port import ConfigCatalogProviderPort
from config_sync.ports.config_changelog_port import ConfigChangelogRepositoryPort
from config_sync.ports.config_watch_client_port import ConfigWatchClientPort, WatchStreamItem


class FakeConfigChangelogRepository(ConfigChangelogRepositoryPort):
    """Deterministic in-memory changelog preserving strict `(txid, version)` total order."""

    def __init__(self, *, shared_tenant_ids: tuple[str, ...] = ()) -> None:
        self._entries: list[ConfigDeltaEvent] = []
        self._next_version: int = 1
        self._shared_tenant_ids = frozenset(shared_tenant_ids)
        self.visible_cursor_cap: ConfigCursor | None = None

    def _visible_entries(self) -> list[ConfigDeltaEvent]:
        ordered = sorted(self._entries, key=lambda entry: entry.cursor)
        if self.visible_cursor_cap is None:
            return ordered
        cap = self.visible_cursor_cap
        return [entry for entry in ordered if entry.cursor <= cap]

    async def append_change(
        self,
        *,
        app_id: str,
        tenant_id: str,
        entity_type: str,
        entity_id: str,
        action: ConfigChangeAction,
        payload: JsonDict,
        event_id: str | None = None,
        txid: int | None = None,
    ) -> ConfigDeltaEvent:
        version = self._next_version
        self._next_version += 1
        resolved_txid = txid if txid is not None else version
        delta = ConfigDeltaEvent(
            event_id=event_id or generate_id(SystemIdPrefix.GENERIC),
            app_id=app_id,
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            version=version,
            txid=resolved_txid,
            checksum=compute_payload_checksum(payload),
            payload=dict(payload),
        )
        self._entries.append(delta)
        return delta

    async def get_latest_cursor(self, *, app_id: str, tenant_id: str) -> ConfigCursor:
        cursors = [
            e.cursor
            for e in self._visible_entries()
            if e.app_id == app_id
            and (e.tenant_id == tenant_id or e.tenant_id in self._shared_tenant_ids)
        ]
        return max(cursors) if cursors else ConfigCursor.zero()

    async def get_global_safe_cursor(self) -> ConfigCursor:
        visible = self._visible_entries()
        return max((entry.cursor for entry in visible), default=ConfigCursor.zero())

    async def get_deltas_since(
        self,
        *,
        app_id: str,
        tenant_id: str,
        since_cursor: ConfigCursor,
        limit: int = 1000,
    ) -> list[ConfigDeltaEvent]:
        matched = [
            e
            for e in self._visible_entries()
            if e.app_id == app_id
            and (e.tenant_id == tenant_id or e.tenant_id in self._shared_tenant_ids)
            and e.cursor > since_cursor
        ]
        return matched[:limit]

    async def get_entries_after_cursor(
        self,
        *,
        since_cursor: ConfigCursor,
        limit: int = 1000,
    ) -> list[ConfigDeltaEvent]:
        matched = [entry for entry in self._visible_entries() if entry.cursor > since_cursor]
        return matched[:limit]

    async def get_visibility_lag_metrics(self) -> ChangelogVisibilityWatermark:
        safe_cursor = await self.get_global_safe_cursor()
        raw_max_cursor = max(
            (entry.cursor for entry in self._entries),
            default=ConfigCursor.zero(),
        )
        return ChangelogVisibilityWatermark(
            safe_cursor=safe_cursor,
            raw_max_cursor=raw_max_cursor,
        )

    async def cleanup_old_entries(self, *, retention_days: int = 30) -> int:
        del retention_days
        return 0


class FakeConfigCatalogProvider(ConfigCatalogProviderPort):
    """In-memory catalog provider serving snapshots and deltas from a fake changelog."""

    def __init__(
        self,
        *,
        app_id: str,
        changelog: ConfigChangelogRepositoryPort,
    ) -> None:
        self._app_id = app_id
        self._changelog = changelog
        self._entities_by_tenant: dict[str, dict[tuple[str, str], ConfigEntityRecord]] = {}

    @property
    def app_id(self) -> str:
        return self._app_id

    def seed_entity(
        self,
        *,
        tenant_id: str,
        entity_type: str,
        entity_id: str,
        payload: JsonDict,
    ) -> ConfigEntityRecord:
        rec = ConfigEntityRecord(
            entity_type=entity_type,
            entity_id=entity_id,
            tenant_id=tenant_id,
            payload=dict(payload),
            checksum=compute_payload_checksum(payload),
        )
        self._entities_by_tenant.setdefault(tenant_id, {})[(entity_type, entity_id)] = rec
        return rec

    async def get_tenant_snapshot(self, *, tenant_id: str) -> ConfigSnapshot:
        entities = tuple(self._entities_by_tenant.get(tenant_id, {}).values())
        cursor = await self._changelog.get_latest_cursor(app_id=self._app_id, tenant_id=tenant_id)
        return ConfigSnapshot(
            app_id=self._app_id,
            tenant_id=tenant_id,
            version=cursor.version,
            txid=cursor.txid,
            entities=entities,
            checksum=compute_snapshot_checksum(entities),
        )

    async def get_deltas_since(
        self, *, tenant_id: str, since_cursor: ConfigCursor
    ) -> list[ConfigDeltaEvent]:
        return await self._changelog.get_deltas_since(
            app_id=self._app_id,
            tenant_id=tenant_id,
            since_cursor=since_cursor,
        )


class FakeConfigWatchClient(ConfigWatchClientPort):
    """Deterministic client yielding a pre-recorded sequence of WatchStreamItems."""

    def __init__(
        self,
        items: Sequence[WatchStreamItem],
        *,
        snapshot: ConfigSnapshot | None = None,
    ) -> None:
        self._items = list(items)
        self._snapshot = snapshot
        self.watch_calls: list[tuple[str, str, ConfigCursor]] = []

    async def fetch_snapshot(
        self,
        *,
        app_id: str,
        tenant_id: str,
    ) -> Result[ConfigSnapshot, ConfigSyncError]:
        if self._snapshot is not None:
            return Result.ok(self._snapshot)
        return Result.fail(
            ConfigSyncError(
                code=ConfigSyncErrorCode.UNKNOWN_APP,
                message=f"No fake snapshot configured for {app_id}/{tenant_id}.",
            )
        )

    async def watch(
        self,
        *,
        app_id: str,
        tenant_id: str,
        since_cursor: ConfigCursor | None = None,
    ) -> AsyncIterator[WatchStreamItem]:
        resolved = since_cursor if since_cursor is not None else ConfigCursor.zero()
        self.watch_calls.append((app_id, tenant_id, resolved))
        for item in self._items:
            yield item


__all__ = [
    "FakeConfigCatalogProvider",
    "FakeConfigChangelogRepository",
    "FakeConfigWatchClient",
]
