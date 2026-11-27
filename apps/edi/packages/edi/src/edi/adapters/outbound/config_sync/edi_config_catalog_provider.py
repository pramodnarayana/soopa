"""EDI Control Plane ConfigCatalogProviderPort serving topological snapshots and deltas."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import ClassVar, Protocol, cast

from database.config_changelog import (
    ensure_repeatable_read_snapshot,
    get_latest_config_changelog_cursor_in_session,
)
from identity.domain.identity_context import PLATFORM_TENANT_ID
from seedwork.domain.types import JsonDict, JsonValue
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped

from config_sync.domain.checksum import compute_payload_checksum, compute_snapshot_checksum
from config_sync.domain.dtos import (
    ConfigCursor,
    ConfigDeltaEvent,
    ConfigEntityRecord,
    ConfigSnapshot,
)
from config_sync.ports.config_catalog_provider_port import ConfigCatalogProviderPort
from config_sync.ports.config_changelog_port import ConfigChangelogRepositoryPort
from edi.adapters.outbound.database.replication_registry import REPLICATION_GRAPH
from edi.domain.enums import EDI_CONFIG_APP_ID
from edi.domain.replication.graph import EntitySpecProtocol, topological_layers

SessionScopeFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

_TOPOLOGICAL_LAYERS: list[list[str]] = topological_layers(REPLICATION_GRAPH)


class _GlobalConfigModel(Protocol):
    __tablename__: ClassVar[str]
    id: Mapped[str]
    tenant_id: Mapped[str | None]


def _normalize_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _normalize_json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_json_value(item) for item in value]
    return str(value)


def _normalize_payload(raw_map: dict[str, object]) -> JsonDict:
    return {str(k): _normalize_json_value(v) for k, v in raw_map.items()}


def _build_snapshot_select(spec: EntitySpecProtocol, tenant_id: str) -> Select[tuple[object]]:
    model = cast(type[_GlobalConfigModel], spec.control_plane_model)
    stmt: Select[tuple[object]] = select(model)
    if spec.include_shared:
        return stmt.where(
            (model.tenant_id == tenant_id) | (model.tenant_id == PLATFORM_TENANT_ID)
        ).order_by(model.id.asc())
    return stmt.where(model.tenant_id == tenant_id).order_by(model.id.asc())


class EdiConfigCatalogProvider(ConfigCatalogProviderPort):
    """Serves full topological EDI tenant snapshots and monotonic catch-up deltas over Dynamic Watch."""

    def __init__(
        self,
        *,
        session_factory: SessionScopeFactory,
        changelog_repo: ConfigChangelogRepositoryPort,
    ) -> None:
        self._session_scope = session_factory
        self._changelog_repo = changelog_repo

    @property
    def app_id(self) -> str:
        return EDI_CONFIG_APP_ID

    async def get_tenant_snapshot(self, *, tenant_id: str) -> ConfigSnapshot:
        entities: list[ConfigEntityRecord] = []
        async with self._session_scope() as session:
            # Lock-free REPEATABLE READ snapshot guarantees FK consistency across all topological layers.
            await ensure_repeatable_read_snapshot(session)
            txid, version = await get_latest_config_changelog_cursor_in_session(
                session,
                app_id=EDI_CONFIG_APP_ID,
                tenant_id=tenant_id,
                shared_tenant_ids=(PLATFORM_TENANT_ID,),
            )
            for layer in _TOPOLOGICAL_LAYERS:
                for entity_key in layer:
                    spec = REPLICATION_GRAPH[entity_key]
                    stmt = _build_snapshot_select(spec, tenant_id)
                    rows = (await session.execute(stmt)).scalars().all()
                    for row in rows:
                        typed_row = cast(_GlobalConfigModel, row)
                        raw_tenant = typed_row.tenant_id
                        source_tenant = str(raw_tenant) if raw_tenant is not None else tenant_id
                        mapped = dict(spec.map_entity(row))
                        if mapped.get("tenant_id") is None:
                            mapped["tenant_id"] = source_tenant
                        payload = _normalize_payload(mapped)
                        entities.append(
                            ConfigEntityRecord(
                                entity_type=entity_key,
                                entity_id=str(typed_row.id),
                                tenant_id=source_tenant,
                                payload=payload,
                                checksum=compute_payload_checksum(payload),
                            )
                        )

        frozen_entities = tuple(entities)
        return ConfigSnapshot(
            app_id=EDI_CONFIG_APP_ID,
            tenant_id=tenant_id,
            version=version,
            txid=txid,
            entities=frozen_entities,
            checksum=compute_snapshot_checksum(frozen_entities),
        )

    async def get_deltas_since(
        self, *, tenant_id: str, since_cursor: ConfigCursor
    ) -> list[ConfigDeltaEvent]:
        return await self._changelog_repo.get_deltas_since(
            app_id=EDI_CONFIG_APP_ID,
            tenant_id=tenant_id,
            since_cursor=since_cursor,
        )


__all__ = ["EDI_CONFIG_APP_ID", "EdiConfigCatalogProvider"]
