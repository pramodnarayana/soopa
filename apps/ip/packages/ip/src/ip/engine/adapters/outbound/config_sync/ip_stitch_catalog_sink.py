"""IP Data Plane ConfigApplySinkPort hydrating StitchCatalogRegistryPort via ReadableConfigSinkPort."""

from __future__ import annotations

import structlog
from ip.engine.domain.enums import IpConfigEntityType
from ip.engine.domain.stitch.stitch import Stitch
from ip.engine.ports.outbound.stitch_catalog_registry_port import (
    StitchCatalogRegistryPort,
)
from seedwork.domain.types import JsonDict, JsonPrimitive

from config_sync.domain.dtos import (
    ConfigCursor,
    ConfigDeltaEvent,
    ConfigEntityRecord,
    ConfigSnapshot,
)
from config_sync.domain.enums import ConfigChangeAction
from config_sync.ports.config_apply_sink_port import (
    ConfigApplySinkPort,
    ReadableConfigSinkPort,
)

logger = structlog.get_logger(__name__)


def _parse_filter_conditions(raw: object) -> dict[str, JsonPrimitive]:
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, JsonPrimitive] = {}
    for k, v in raw.items():
        if v is None or isinstance(v, (str, int, float, bool)):
            cleaned[str(k)] = v
    return cleaned


def _payload_to_stitch(entity_id: str, tenant_id: str, payload: JsonDict) -> Stitch:
    raw_mapping_spec = payload.get("mapping_spec_id")
    raw_linked = payload.get("linked_stitch_id")
    raw_active = payload.get("is_active", True)
    return Stitch(
        id=str(payload.get("id") or entity_id),
        tenant_id=str(payload.get("tenant_id") or tenant_id),
        canonical_event_type=str(payload.get("canonical_event_type", "")),
        target_workflow_id=str(payload.get("target_workflow_id", "")),
        name=str(payload.get("name", "")),
        description=str(payload.get("description", "")),
        mapping_spec_id=raw_mapping_spec if isinstance(raw_mapping_spec, str) else None,
        filter_conditions=_parse_filter_conditions(payload.get("filter_conditions")),
        is_active=bool(raw_active) if isinstance(raw_active, bool) else True,
        idempotency_key_field=str(payload.get("idempotency_key_field", "")),
        concurrency_key_field=str(payload.get("concurrency_key_field", "")),
        linked_stitch_id=raw_linked if isinstance(raw_linked, str) else None,
    )


class IpStitchCatalogSink(ConfigApplySinkPort):
    """Applies verified IP Dynamic Watch snapshots & deltas into `StitchCatalogRegistryPort` + LKG sink.

    Strictly adheres to Zero Adapter-to-Adapter Coupling: both `stitch_catalog` and `backing_sink`
    are injected as abstract Ports assembled by the Composition Root.
    """

    def __init__(
        self,
        *,
        stitch_catalog: StitchCatalogRegistryPort,
        backing_sink: ReadableConfigSinkPort,
        tenant_id: str,
    ) -> None:
        self._stitch_catalog = stitch_catalog
        self._backing_sink = backing_sink
        self._tenant_id = tenant_id
        if not self._backing_sink.current_cursor.is_zero:
            self._rebuild_stitch_catalog(
                self._backing_sink.list_by_type(IpConfigEntityType.STITCH.value)
            )

    def _rebuild_stitch_catalog(self, stitch_records: tuple[ConfigEntityRecord, ...]) -> None:
        existing_keys = {
            (s.tenant_id, s.id)
            for s in self._stitch_catalog.list_stitches(tenant_id=self._tenant_id)
            if s.tenant_id == self._tenant_id
        }
        incoming_keys: set[tuple[str, str]] = set()
        for rec in stitch_records:
            stitch = _payload_to_stitch(rec.entity_id, rec.tenant_id, rec.payload)
            self._stitch_catalog.register_stitch(stitch)
            incoming_keys.add((stitch.tenant_id, stitch.id))
        for stale_tenant, stale_id in existing_keys - incoming_keys:
            self._stitch_catalog.unregister_stitch(tenant_id=stale_tenant, stitch_id=stale_id)

    async def get_current_cursor(self, *, app_id: str, tenant_id: str) -> ConfigCursor:
        return await self._backing_sink.get_current_cursor(app_id=app_id, tenant_id=tenant_id)

    async def apply_snapshot(self, snapshot: ConfigSnapshot) -> None:
        await self._backing_sink.apply_snapshot(snapshot)
        stitch_records = self._backing_sink.list_by_type(IpConfigEntityType.STITCH.value)
        self._rebuild_stitch_catalog(stitch_records)
        logger.info(
            "ip_stitch_catalog_snapshot_applied",
            tenant_id=self._tenant_id,
            cursor=snapshot.cursor.encode(),
            stitch_count=len(stitch_records),
        )

    async def apply_delta(self, delta: ConfigDeltaEvent) -> None:
        prev_cursor = self._backing_sink.current_cursor
        await self._backing_sink.apply_delta(delta)
        if self._backing_sink.current_cursor <= prev_cursor:
            return
        if delta.entity_type == IpConfigEntityType.STITCH.value:
            if delta.action == ConfigChangeAction.DELETE:
                self._stitch_catalog.unregister_stitch(
                    tenant_id=delta.tenant_id,
                    stitch_id=delta.entity_id,
                )
            else:
                stitch = _payload_to_stitch(delta.entity_id, delta.tenant_id, delta.payload)
                self._stitch_catalog.register_stitch(stitch)
            logger.info(
                "ip_stitch_catalog_delta_applied",
                tenant_id=delta.tenant_id,
                stitch_id=delta.entity_id,
                action=delta.action.value,
                version=delta.version,
            )


__all__ = ["IpStitchCatalogSink"]
