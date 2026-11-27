"""Pure Monotonic Version Guard enforcing zero-lock convergence on Data Plane shards."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from config_sync.domain.checksum import verify_delta_checksum, verify_snapshot_checksum
from config_sync.domain.dtos import (
    ConfigCursor,
    ConfigDeltaEvent,
    ConfigEntityRecord,
    ConfigSnapshot,
)
from config_sync.domain.enums import ConfigChangeAction

EntityKey = tuple[str, str, str]  # (entity_type, tenant_id, entity_id)


@dataclass(frozen=True)
class DeltaApplyDecision:
    """First-class outcome of evaluating a delta against the monotonic `(txid, version)` invariant."""

    applied: bool
    reason: str
    cursor: ConfigCursor

    @property
    def version(self) -> int:
        return self.cursor.version


class MonotonicCatalogState:
    """Pure immutable-pointer catalog state enforcing `Cursor(E) > Cursor(local)` with atomic swaps.

    Reads observe an immutable `MappingProxyType` reference (zero locks, sub-microsecond).
    Writes construct a new dict and atomically swap the single Python reference.
    """

    def __init__(self, *, app_id: str, tenant_id: str) -> None:
        self.app_id = app_id
        self.tenant_id = tenant_id
        self._cursor: ConfigCursor = ConfigCursor.zero()
        self._entity_cursors: dict[EntityKey, ConfigCursor] = {}
        self._entities: MappingProxyType[EntityKey, ConfigEntityRecord] = MappingProxyType({})

    @property
    def current_cursor(self) -> ConfigCursor:
        return self._cursor

    @property
    def current_version(self) -> int:
        return self._cursor.version

    @property
    def entities(self) -> MappingProxyType[EntityKey, ConfigEntityRecord]:
        return self._entities

    def list_by_type(self, entity_type: str) -> tuple[ConfigEntityRecord, ...]:
        snapshot_ref = self._entities
        return tuple(rec for rec in snapshot_ref.values() if rec.entity_type == entity_type)

    def get_entity(
        self, entity_type: str, tenant_id: str, entity_id: str
    ) -> ConfigEntityRecord | None:
        return self._entities.get((entity_type, tenant_id, entity_id))

    def apply_snapshot(self, snapshot: ConfigSnapshot) -> DeltaApplyDecision:
        """Atomically replaces the catalog with a verified authoritative baseline snapshot."""
        if not verify_snapshot_checksum(snapshot):
            return DeltaApplyDecision(
                applied=False,
                reason="snapshot_checksum_mismatch",
                cursor=self._cursor,
            )
        if snapshot.cursor < self._cursor:
            return DeltaApplyDecision(
                applied=False,
                reason="stale_snapshot_dropped",
                cursor=self._cursor,
            )

        next_entities: dict[EntityKey, ConfigEntityRecord] = {}
        next_cursors: dict[EntityKey, ConfigCursor] = {}
        for rec in snapshot.entities:
            key: EntityKey = (rec.entity_type, rec.tenant_id, rec.entity_id)
            next_entities[key] = rec
            next_cursors[key] = snapshot.cursor

        self._entities = MappingProxyType(next_entities)
        self._entity_cursors = next_cursors
        self._cursor = snapshot.cursor
        return DeltaApplyDecision(
            applied=True,
            reason="snapshot_applied",
            cursor=self._cursor,
        )

    def apply_delta(self, event: ConfigDeltaEvent) -> DeltaApplyDecision:
        """Applies a single delta iff checksum is valid and `event.cursor > local_cursor`."""
        if not verify_delta_checksum(event):
            return DeltaApplyDecision(
                applied=False,
                reason="delta_checksum_mismatch",
                cursor=self._cursor,
            )
        key: EntityKey = (event.entity_type, event.tenant_id, event.entity_id)
        entity_cursor = self._entity_cursors.get(key, ConfigCursor.zero())
        if event.cursor <= entity_cursor or event.cursor <= self._cursor:
            return DeltaApplyDecision(
                applied=False,
                reason="stale_version_dropped",
                cursor=self._cursor,
            )

        next_entities = dict(self._entities)
        if event.action == ConfigChangeAction.DELETE:
            next_entities.pop(key, None)
        else:
            next_entities[key] = ConfigEntityRecord(
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                tenant_id=event.tenant_id,
                payload=event.payload,
                checksum=event.checksum,
            )

        self._entity_cursors[key] = event.cursor
        self._entities = MappingProxyType(next_entities)
        self._cursor = event.cursor
        return DeltaApplyDecision(
            applied=True,
            reason="delta_applied",
            cursor=self._cursor,
        )


__all__ = ["DeltaApplyDecision", "EntityKey", "MonotonicCatalogState"]
