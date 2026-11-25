"""Pure Monotonic Version Guard enforcing zero-lock convergence on Data Plane shards."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from config_sync.domain.checksum import verify_delta_checksum, verify_snapshot_checksum
from config_sync.domain.dtos import ConfigDeltaEvent, ConfigEntityRecord, ConfigSnapshot
from config_sync.domain.enums import ConfigChangeAction

EntityKey = tuple[str, str, str]  # (entity_type, tenant_id, entity_id)


@dataclass(frozen=True)
class DeltaApplyDecision:
    """First-class outcome of evaluating a delta against the monotonic invariant."""

    applied: bool
    reason: str
    version: int


class MonotonicCatalogState:
    """Pure immutable-pointer catalog state enforcing `V(E) > V(local)` with atomic swaps.

    Reads observe an immutable `MappingProxyType` reference (zero locks, sub-microsecond).
    Writes construct a new dict and atomically swap the single Python reference.
    """

    def __init__(self, *, app_id: str, tenant_id: str) -> None:
        self.app_id = app_id
        self.tenant_id = tenant_id
        self._version: int = 0
        self._entity_versions: dict[EntityKey, int] = {}
        self._entities: MappingProxyType[EntityKey, ConfigEntityRecord] = MappingProxyType({})

    @property
    def current_version(self) -> int:
        return self._version

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
                version=self._version,
            )
        if snapshot.version < self._version:
            return DeltaApplyDecision(
                applied=False,
                reason="stale_snapshot_dropped",
                version=self._version,
            )

        next_entities: dict[EntityKey, ConfigEntityRecord] = {}
        next_versions: dict[EntityKey, int] = {}
        for rec in snapshot.entities:
            key: EntityKey = (rec.entity_type, rec.tenant_id, rec.entity_id)
            next_entities[key] = rec
            next_versions[key] = snapshot.version

        self._entities = MappingProxyType(next_entities)
        self._entity_versions = next_versions
        self._version = snapshot.version
        return DeltaApplyDecision(
            applied=True,
            reason="snapshot_applied",
            version=self._version,
        )

    def apply_delta(self, event: ConfigDeltaEvent) -> DeltaApplyDecision:
        """Applies a single delta iff checksum is valid and `event.version > local_version`."""
        if not verify_delta_checksum(event):
            return DeltaApplyDecision(
                applied=False,
                reason="delta_checksum_mismatch",
                version=self._version,
            )
        key: EntityKey = (event.entity_type, event.tenant_id, event.entity_id)
        entity_ver = self._entity_versions.get(key, 0)
        if event.version <= entity_ver or event.version <= self._version:
            return DeltaApplyDecision(
                applied=False,
                reason="stale_version_dropped",
                version=self._version,
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

        self._entity_versions[key] = event.version
        self._entities = MappingProxyType(next_entities)
        self._version = event.version
        return DeltaApplyDecision(
            applied=True,
            reason="delta_applied",
            version=self._version,
        )


__all__ = ["DeltaApplyDecision", "EntityKey", "MonotonicCatalogState"]
