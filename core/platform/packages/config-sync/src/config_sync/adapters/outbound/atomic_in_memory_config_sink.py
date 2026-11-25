"""Atomic In-Memory Config Sink with optional Last-Known-Good (LKG) disk checkpoint for outage survivability."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path
from types import MappingProxyType

import structlog

from config_sync.domain.checksum import compute_snapshot_checksum
from config_sync.domain.dtos import ConfigDeltaEvent, ConfigEntityRecord, ConfigSnapshot
from config_sync.domain.monotonic_guard import EntityKey, MonotonicCatalogState
from config_sync.ports.config_apply_sink_port import ConfigApplySinkPort

logger = structlog.get_logger(__name__)


class AtomicInMemoryConfigSink(ConfigApplySinkPort):
    """Zero-lock atomic pointer-swap Data Plane catalog sink with optional `0o600` LKG disk persistence."""

    def __init__(
        self,
        *,
        app_id: str,
        tenant_id: str,
        lkg_file_path: str | Path | None = None,
    ) -> None:
        self._state = MonotonicCatalogState(app_id=app_id, tenant_id=tenant_id)
        self._lkg_path: Path | None = Path(lkg_file_path) if lkg_file_path is not None else None
        if self._lkg_path is not None and self._lkg_path.is_file():
            self._load_lkg_sync()

    @property
    def current_version(self) -> int:
        return self._state.current_version

    @property
    def entities(self) -> MappingProxyType[EntityKey, ConfigEntityRecord]:
        return self._state.entities

    def list_by_type(self, entity_type: str) -> tuple[ConfigEntityRecord, ...]:
        return self._state.list_by_type(entity_type)

    def get_entity(
        self, entity_type: str, tenant_id: str, entity_id: str
    ) -> ConfigEntityRecord | None:
        return self._state.get_entity(entity_type, tenant_id, entity_id)

    async def get_current_version(self, *, app_id: str, tenant_id: str) -> int:
        del app_id, tenant_id
        return self._state.current_version

    async def apply_snapshot(self, snapshot: ConfigSnapshot) -> None:
        decision = self._state.apply_snapshot(snapshot)
        if decision.applied and self._lkg_path is not None:
            await asyncio.to_thread(self._persist_lkg_sync)

    async def apply_delta(self, delta: ConfigDeltaEvent) -> None:
        decision = self._state.apply_delta(delta)
        if decision.applied and self._lkg_path is not None:
            await asyncio.to_thread(self._persist_lkg_sync)

    def _load_lkg_sync(self) -> None:
        if self._lkg_path is None:
            return
        try:
            raw = json.loads(self._lkg_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return
            entities: list[ConfigEntityRecord] = []
            for item in raw.get("entities", []):
                if not isinstance(item, dict):
                    continue
                payload = item.get("payload")
                if not isinstance(payload, dict):
                    continue
                entities.append(
                    ConfigEntityRecord(
                        entity_type=str(item["entity_type"]),
                        entity_id=str(item["entity_id"]),
                        tenant_id=str(item["tenant_id"]),
                        checksum=str(item["checksum"]),
                        payload=dict(payload),
                    )
                )
            snapshot = ConfigSnapshot(
                app_id=str(raw.get("app_id", self._state.app_id)),
                tenant_id=str(raw.get("tenant_id", self._state.tenant_id)),
                version=int(raw.get("version", 0)),
                entities=tuple(entities),
                checksum=str(raw.get("checksum", "")),
            )
            decision = self._state.apply_snapshot(snapshot)
            logger.info(
                "config_sync_lkg_loaded",
                app_id=self._state.app_id,
                tenant_id=self._state.tenant_id,
                version=decision.version,
                applied=decision.applied,
            )
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.error(
                "config_sync_lkg_load_failed",
                path=str(self._lkg_path),
                error=str(exc),
            )

    def _persist_lkg_sync(self) -> None:
        if self._lkg_path is None:
            return
        entities = tuple(self._state.entities.values())
        payload = {
            "app_id": self._state.app_id,
            "tenant_id": self._state.tenant_id,
            "version": self._state.current_version,
            "checksum": compute_snapshot_checksum(entities),
            "entities": [
                {
                    "entity_type": e.entity_type,
                    "entity_id": e.entity_id,
                    "tenant_id": e.tenant_id,
                    "checksum": e.checksum,
                    "payload": e.payload,
                }
                for e in entities
            ],
        }
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
        self._lkg_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._lkg_path.with_name(
            f".{self._lkg_path.name}.{os.getpid()}.{os.urandom(6).hex()}.tmp"
        )
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        written = False
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self._lkg_path)
            written = True
        finally:
            if not written:
                with contextlib.suppress(OSError):
                    temp_path.unlink(missing_ok=True)


__all__ = ["AtomicInMemoryConfigSink"]
