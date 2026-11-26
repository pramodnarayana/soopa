"""Use Case streaming unified cold-start snapshots, catch-up deltas, and live SSE frames."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog
from seedwork.domain.exceptions import Result
from seedwork.domain.types import JsonDict, JsonValue

from config_sync.application.config_catalog_registry import ConfigCatalogRegistry
from config_sync.domain.dtos import (
    ConfigCursor,
    ConfigDeltaEvent,
    ConfigSnapshot,
    ConfigSyncError,
    ConfigWatchFrame,
)
from config_sync.domain.enums import ConfigWatchEventType
from config_sync.ports.config_broadcaster_port import ConfigBroadcasterPort
from config_sync.ports.config_catalog_provider_port import ConfigCatalogProviderPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class StreamConfigWatchQuery:
    """Co-located Query DTO for opening a Dynamic Watch stream."""

    app_id: str
    tenant_id: str
    since_cursor: ConfigCursor = field(default_factory=ConfigCursor.zero)
    chunk_size: int = 100
    heartbeat_interval_seconds: float = 15.0
    max_events: int | None = None


def _delta_to_payload(delta: ConfigDeltaEvent) -> JsonDict:
    return {
        "event_id": delta.event_id,
        "app_id": delta.app_id,
        "tenant_id": delta.tenant_id,
        "entity_type": delta.entity_type,
        "entity_id": delta.entity_id,
        "action": delta.action.value,
        "txid": delta.txid,
        "version": delta.version,
        "cursor": delta.cursor.encode(),
        "checksum": delta.checksum,
        "payload": delta.payload,
    }


def _snapshot_frames(snapshot: ConfigSnapshot, chunk_size: int) -> list[ConfigWatchFrame]:
    effective_chunk = max(1, chunk_size)
    frames: list[ConfigWatchFrame] = [
        ConfigWatchFrame(
            event=ConfigWatchEventType.SNAPSHOT_START.value,
            data={
                "app_id": snapshot.app_id,
                "tenant_id": snapshot.tenant_id,
                "base_txid": snapshot.txid,
                "base_version": snapshot.version,
                "total_entities": len(snapshot.entities),
            },
        )
    ]
    for offset in range(0, len(snapshot.entities), effective_chunk):
        batch = snapshot.entities[offset : offset + effective_chunk]
        serialized: list[JsonValue] = [
            {
                "entity_type": rec.entity_type,
                "entity_id": rec.entity_id,
                "tenant_id": rec.tenant_id,
                "checksum": rec.checksum,
                "payload": rec.payload,
            }
            for rec in batch
        ]
        frames.append(
            ConfigWatchFrame(
                event=ConfigWatchEventType.SNAPSHOT_CHUNK.value,
                data={"entities": serialized},
            )
        )
    frames.append(
        ConfigWatchFrame(
            event=ConfigWatchEventType.SNAPSHOT_END.value,
            data={
                "app_id": snapshot.app_id,
                "tenant_id": snapshot.tenant_id,
                "final_txid": snapshot.txid,
                "final_version": snapshot.version,
                "cursor": snapshot.cursor.encode(),
                "checksum": snapshot.checksum,
            },
            frame_id=snapshot.cursor.encode(),
        )
    )
    return frames


class StreamConfigWatchUseCase:
    """Orchestrates unified cold-start snapshot, catch-up delta replay, and live broadcast streaming."""

    def __init__(
        self,
        *,
        registry: ConfigCatalogRegistry,
        broadcaster: ConfigBroadcasterPort,
    ) -> None:
        self._registry = registry
        self._broadcaster = broadcaster

    def resolve_provider(self, app_id: str) -> Result[ConfigCatalogProviderPort, ConfigSyncError]:
        return self._registry.resolve(app_id)

    async def get_snapshot(
        self, *, app_id: str, tenant_id: str
    ) -> Result[ConfigSnapshot, ConfigSyncError]:
        provider_res = self._registry.resolve(app_id)
        if provider_res.is_err:
            return Result.fail(provider_res.unwrap_err())
        snapshot = await provider_res.unwrap().get_tenant_snapshot(tenant_id=tenant_id)
        return Result.ok(snapshot)

    async def _initial_sync_frames(
        self,
        provider: ConfigCatalogProviderPort,
        query: StreamConfigWatchQuery,
    ) -> tuple[list[ConfigWatchFrame], ConfigCursor]:
        if query.since_cursor.is_zero:
            snapshot = await provider.get_tenant_snapshot(tenant_id=query.tenant_id)
            return _snapshot_frames(snapshot, query.chunk_size), snapshot.cursor

        buffered = self._broadcaster.get_buffered_deltas_since(
            app_id=provider.app_id,
            tenant_id=query.tenant_id,
            since_cursor=query.since_cursor,
        )
        if buffered is not None:
            frames = [
                ConfigWatchFrame(
                    event=ConfigWatchEventType.DELTA.value,
                    data=_delta_to_payload(delta),
                    frame_id=delta.cursor.encode(),
                )
                for delta in buffered
            ]
            last_cursor = buffered[-1].cursor if buffered else query.since_cursor
            return frames, last_cursor

        db_deltas = await provider.get_deltas_since(
            tenant_id=query.tenant_id,
            since_cursor=query.since_cursor,
        )
        if db_deltas:
            frames = [
                ConfigWatchFrame(
                    event=ConfigWatchEventType.DELTA.value,
                    data=_delta_to_payload(delta),
                    frame_id=delta.cursor.encode(),
                )
                for delta in db_deltas
            ]
            return frames, db_deltas[-1].cursor

        # Either already up-to-date or evicted beyond DB retention: check snapshot cursor
        snapshot = await provider.get_tenant_snapshot(tenant_id=query.tenant_id)
        if snapshot.cursor <= query.since_cursor:
            return [], query.since_cursor
        return _snapshot_frames(snapshot, query.chunk_size), snapshot.cursor

    async def stream(
        self,
        provider: ConfigCatalogProviderPort,
        query: StreamConfigWatchQuery,
    ) -> AsyncIterator[ConfigWatchFrame]:
        """Subscribes BEFORE reading snapshot/deltas so zero concurrent mutations can be missed."""
        bound = logger.bind(
            app_id=provider.app_id,
            tenant_id=query.tenant_id,
            since_cursor=query.since_cursor.encode(),
        )
        bound.info("config_watch_stream_started")
        emitted = 0

        async with self._broadcaster.subscribe(
            app_id=provider.app_id,
            tenant_id=query.tenant_id,
        ) as live_iter:
            initial_frames, last_cursor = await self._initial_sync_frames(provider, query)
            for frame in initial_frames:
                yield frame
                emitted += 1
                if query.max_events is not None and emitted >= query.max_events:
                    return

            async_iter = live_iter.__aiter__()
            while query.max_events is None or emitted < query.max_events:
                try:
                    delta = await asyncio.wait_for(
                        async_iter.__anext__(),
                        timeout=query.heartbeat_interval_seconds,
                    )
                except TimeoutError:
                    missed_deltas = await provider.get_deltas_since(
                        tenant_id=query.tenant_id,
                        since_cursor=last_cursor,
                    )
                    for missed in missed_deltas:
                        if missed.cursor <= last_cursor:
                            continue
                        last_cursor = missed.cursor
                        yield ConfigWatchFrame(
                            event=ConfigWatchEventType.DELTA.value,
                            data=_delta_to_payload(missed),
                            frame_id=missed.cursor.encode(),
                        )
                        emitted += 1
                        if query.max_events is not None and emitted >= query.max_events:
                            return
                    yield ConfigWatchFrame(
                        event=ConfigWatchEventType.HEARTBEAT.value,
                        data={
                            "app_id": provider.app_id,
                            "tenant_id": query.tenant_id,
                            "latest_txid": last_cursor.txid,
                            "latest_version": last_cursor.version,
                            "latest_cursor": last_cursor.encode(),
                            "timestamp": datetime.now(UTC).isoformat(),
                        },
                    )
                    emitted += 1
                    continue
                except StopAsyncIteration:
                    break

                if delta.cursor <= last_cursor:
                    continue

                last_cursor = delta.cursor
                yield ConfigWatchFrame(
                    event=ConfigWatchEventType.DELTA.value,
                    data=_delta_to_payload(delta),
                    frame_id=delta.cursor.encode(),
                )
                emitted += 1

        bound.info(
            "config_watch_stream_ended",
            last_cursor=last_cursor.encode(),
            emitted_frames=emitted,
        )


__all__ = ["StreamConfigWatchQuery", "StreamConfigWatchUseCase"]
