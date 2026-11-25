"""EDI Data Plane Shard ConfigApplySinkPort applying Dynamic Watch snapshots & deltas atomically."""

from __future__ import annotations

from contextlib import aclosing
from datetime import datetime
from typing import ClassVar, Protocol, cast

import structlog
from database.router import DatabaseRouterPort
from seedwork.domain.types import JsonDict
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped

from config_sync.domain.dtos import ConfigDeltaEvent, ConfigEntityRecord, ConfigSnapshot
from config_sync.domain.enums import ConfigChangeAction
from config_sync.domain.monotonic_guard import MonotonicCatalogState
from config_sync.ports.config_apply_sink_port import ConfigApplySinkPort
from edi.adapters.outbound.database.replication_registry import REPLICATION_GRAPH
from edi.domain.enums import EDI_CONFIG_APP_ID
from edi.domain.replication.graph import topological_layers
from edi.ports.outbound.tenant_port import TenantPort

logger = structlog.get_logger(__name__)

_TOPOLOGICAL_LAYERS: list[list[str]] = topological_layers(REPLICATION_GRAPH)
_REVERSE_TOPOLOGICAL_LAYERS: list[list[str]] = list(reversed(_TOPOLOGICAL_LAYERS))
_DATETIME_COLUMNS: frozenset[str] = frozenset({"created_at", "updated_at"})


class _ShardConfigModel(Protocol):
    __tablename__: ClassVar[str]
    id: Mapped[str]
    tenant_id: Mapped[str | None]


def _coerce_row_values(payload: JsonDict) -> dict[str, object]:
    row: dict[str, object] = {}
    for key, val in payload.items():
        if key in _DATETIME_COLUMNS and isinstance(val, str):
            row[key] = datetime.fromisoformat(val)
        else:
            row[key] = val
    return row


async def _upsert_rows(
    session: AsyncSession,
    model_cls: type[DeclarativeBase],
    rows: list[dict[str, object]],
) -> None:
    if not rows:
        return
    stmt = pg_insert(model_cls).values(rows)
    update_cols = {
        col.name: stmt.excluded[col.name]
        for col in model_cls.__table__.columns
        if not col.primary_key
    }
    await session.execute(stmt.on_conflict_do_update(index_elements=["id"], set_=update_cols))


class EdiShardConfigSink(ConfigApplySinkPort):
    """Applies verified EDI Dynamic Watch snapshots & deltas to the tenant shard DB + in-memory mirror."""

    def __init__(
        self,
        *,
        db_router: DatabaseRouterPort,
        tenant_port: TenantPort,
        tenant_id: str,
    ) -> None:
        self._db_router = db_router
        self._tenant_port = tenant_port
        self._tenant_id = tenant_id
        self._mirror = MonotonicCatalogState(app_id=EDI_CONFIG_APP_ID, tenant_id=tenant_id)

    @property
    def mirror(self) -> MonotonicCatalogState:
        return self._mirror

    async def get_current_version(self, *, app_id: str, tenant_id: str) -> int:
        del app_id, tenant_id
        return self._mirror.current_version

    async def apply_snapshot(self, snapshot: ConfigSnapshot) -> None:
        shard_name, shard_dsn = await self._tenant_port.resolve_shard(self._tenant_id)
        by_type: dict[str, list[ConfigEntityRecord]] = {}
        for rec in snapshot.entities:
            by_type.setdefault(rec.entity_type, []).append(rec)

        tenant_gen = self._db_router.get_tenant_session(self._tenant_id, shard_name, shard_dsn)
        async with aclosing(tenant_gen) as tenant_ctx:
            session = await tenant_ctx.__anext__()
            try:
                for layer in _TOPOLOGICAL_LAYERS:
                    for entity_key in layer:
                        spec = REPLICATION_GRAPH[entity_key]
                        records = by_type.get(entity_key, [])
                        if records:
                            rows = [_coerce_row_values(r.payload) for r in records]
                            await _upsert_rows(
                                session,
                                cast(type[DeclarativeBase], spec.data_plane_model),
                                rows,
                            )
                        await session.flush()

                for layer in _REVERSE_TOPOLOGICAL_LAYERS:
                    for entity_key in layer:
                        spec = REPLICATION_GRAPH[entity_key]
                        dp_model = cast(type[_ShardConfigModel], spec.data_plane_model)
                        keep_ids = {
                            r.entity_id
                            for r in by_type.get(entity_key, [])
                            if r.tenant_id == self._tenant_id
                        }
                        del_stmt = delete(dp_model).where(dp_model.tenant_id == self._tenant_id)
                        if keep_ids:
                            del_stmt = del_stmt.where(dp_model.id.not_in(list(keep_ids)))
                        await session.execute(del_stmt)

                await session.commit()
            except Exception:
                await session.rollback()
                raise

        self._mirror.apply_snapshot(snapshot)
        logger.info(
            "edi_shard_config_snapshot_applied",
            tenant_id=self._tenant_id,
            version=snapshot.version,
            entity_count=len(snapshot.entities),
        )

    async def apply_delta(self, delta: ConfigDeltaEvent) -> None:
        if delta.version <= self._mirror.current_version:
            logger.debug(
                "edi_shard_config_delta_dropped_stale",
                tenant_id=self._tenant_id,
                entity_type=delta.entity_type,
                entity_id=delta.entity_id,
                incoming_version=delta.version,
                current_version=self._mirror.current_version,
            )
            return

        spec = REPLICATION_GRAPH.get(delta.entity_type)
        if spec is None:
            logger.error(
                "edi_shard_config_delta_unknown_entity_type",
                tenant_id=self._tenant_id,
                entity_type=delta.entity_type,
                entity_id=delta.entity_id,
            )
            return

        shard_name, shard_dsn = await self._tenant_port.resolve_shard(self._tenant_id)
        tenant_gen = self._db_router.get_tenant_session(self._tenant_id, shard_name, shard_dsn)
        async with aclosing(tenant_gen) as tenant_ctx:
            session = await tenant_ctx.__anext__()
            try:
                if delta.action == ConfigChangeAction.DELETE:
                    dp_model = cast(type[_ShardConfigModel], spec.data_plane_model)
                    await session.execute(
                        delete(dp_model).where(
                            dp_model.id == delta.entity_id,
                            dp_model.tenant_id == delta.tenant_id,
                        )
                    )
                else:
                    row = _coerce_row_values(delta.payload)
                    if row.get("id") is None:
                        row["id"] = delta.entity_id
                    if row.get("tenant_id") is None:
                        row["tenant_id"] = delta.tenant_id
                    await _upsert_rows(
                        session,
                        cast(type[DeclarativeBase], spec.data_plane_model),
                        [row],
                    )
                await session.commit()
            except Exception:
                await session.rollback()
                raise

        self._mirror.apply_delta(delta)
        logger.info(
            "edi_shard_config_delta_applied",
            tenant_id=self._tenant_id,
            entity_type=delta.entity_type,
            entity_id=delta.entity_id,
            action=delta.action.value,
            version=delta.version,
        )


__all__ = ["EdiShardConfigSink"]
