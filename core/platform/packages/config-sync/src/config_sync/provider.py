"""Composition Root helpers assembling Universal Dynamic Watch components."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import httpx

from config_sync.adapters.inbound.changelog_cursor_broadcaster_bridge import (
    ChangelogCursorBroadcasterBridge,
)
from config_sync.adapters.outbound.atomic_in_memory_config_sink import AtomicInMemoryConfigSink
from config_sync.adapters.outbound.httpx_sse_config_watch_client import HttpxSseConfigWatchClient
from config_sync.adapters.outbound.in_memory_ring_buffer_broadcaster import (
    InMemoryRingBufferBroadcaster,
)
from config_sync.adapters.outbound.sqlalchemy_config_changelog_repository import (
    SessionScopeFactory,
    SqlAlchemyConfigChangelogRepository,
)
from config_sync.application.config_catalog_registry import ConfigCatalogRegistry
from config_sync.application.multi_tenant_watch_manager import (
    MultiTenantConfigWatchManager,
    TenantIdsProvider,
    TenantSinkFactory,
)
from config_sync.application.stream_config_watch_use_case import StreamConfigWatchUseCase
from config_sync.application.sync_config_watch_loop_use_case import (
    SyncConfigWatchLoopUseCase,
    WatchLoopConfig,
)
from config_sync.domain.dtos import ConfigCursor
from config_sync.ports.config_apply_sink_port import ConfigApplySinkPort
from config_sync.ports.config_broadcaster_port import ConfigBroadcasterPort
from config_sync.ports.config_catalog_provider_port import ConfigCatalogProviderPort
from config_sync.ports.config_changelog_port import ConfigChangelogRepositoryPort
from config_sync.ports.config_watch_client_port import ConfigWatchClientPort


class ConfigSyncProvider:
    """Universal Platform Composition Root for Queue-Free HTTPS Dynamic Watch."""

    @staticmethod
    def create_changelog_repository(
        *,
        session_factory: SessionScopeFactory,
        shared_tenant_ids: tuple[str, ...] = (),
    ) -> SqlAlchemyConfigChangelogRepository:
        return SqlAlchemyConfigChangelogRepository(
            session_factory=session_factory,
            shared_tenant_ids=shared_tenant_ids,
        )

    @staticmethod
    def create_broadcaster(
        *,
        ring_buffer_size: int = 1000,
        subscriber_queue_maxsize: int = 256,
        broadcast_tenant_ids: tuple[str, ...] = (),
    ) -> InMemoryRingBufferBroadcaster:
        return InMemoryRingBufferBroadcaster(
            ring_buffer_size=ring_buffer_size,
            subscriber_queue_maxsize=subscriber_queue_maxsize,
            broadcast_tenant_ids=broadcast_tenant_ids,
        )

    @staticmethod
    def create_cursor_broadcaster_bridge(
        *,
        changelog_repo: ConfigChangelogRepositoryPort,
        broadcaster: ConfigBroadcasterPort,
        poll_interval_seconds: float = 0.15,
        batch_size: int = 500,
        error_backoff_seconds: float = 1.0,
        initial_cursor: ConfigCursor | None = None,
    ) -> ChangelogCursorBroadcasterBridge:
        return ChangelogCursorBroadcasterBridge(
            changelog_repo=changelog_repo,
            broadcaster=broadcaster,
            poll_interval_seconds=poll_interval_seconds,
            batch_size=batch_size,
            error_backoff_seconds=error_backoff_seconds,
            initial_cursor=initial_cursor,
        )

    @staticmethod
    def create_stream_use_case(
        *,
        providers: Iterable[ConfigCatalogProviderPort],
        broadcaster: ConfigBroadcasterPort,
    ) -> StreamConfigWatchUseCase:
        registry = ConfigCatalogRegistry(providers=providers)
        return StreamConfigWatchUseCase(registry=registry, broadcaster=broadcaster)

    @staticmethod
    def create_sse_watch_client(
        *,
        base_url: str,
        bearer_token: str | None = None,
        timeout_seconds: float = 45.0,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> HttpxSseConfigWatchClient:
        return HttpxSseConfigWatchClient(
            base_url=base_url,
            bearer_token=bearer_token,
            timeout_seconds=timeout_seconds,
            http_transport=http_transport,
        )

    @staticmethod
    def create_in_memory_sink(
        *,
        app_id: str,
        tenant_id: str,
        lkg_file_path: str | Path | None = None,
    ) -> AtomicInMemoryConfigSink:
        return AtomicInMemoryConfigSink(
            app_id=app_id,
            tenant_id=tenant_id,
            lkg_file_path=lkg_file_path,
        )

    @staticmethod
    def create_watch_loop(
        *,
        watch_client: ConfigWatchClientPort,
        sink: ConfigApplySinkPort,
        app_id: str,
        tenant_id: str,
        initial_backoff_seconds: float = 0.1,
        max_backoff_seconds: float = 5.0,
    ) -> SyncConfigWatchLoopUseCase:
        return SyncConfigWatchLoopUseCase(
            watch_client=watch_client,
            sink=sink,
            config=WatchLoopConfig(
                app_id=app_id,
                tenant_id=tenant_id,
                initial_backoff_seconds=initial_backoff_seconds,
                max_backoff_seconds=max_backoff_seconds,
            ),
        )

    @staticmethod
    def create_multi_tenant_watch_manager(
        *,
        app_id: str,
        watch_client: ConfigWatchClientPort,
        tenant_ids_provider: TenantIdsProvider,
        sink_factory: TenantSinkFactory,
        discovery_interval_seconds: float = 30.0,
        initial_backoff_seconds: float = 0.1,
        max_backoff_seconds: float = 5.0,
    ) -> MultiTenantConfigWatchManager:
        return MultiTenantConfigWatchManager(
            app_id=app_id,
            watch_client=watch_client,
            tenant_ids_provider=tenant_ids_provider,
            sink_factory=sink_factory,
            discovery_interval_seconds=discovery_interval_seconds,
            initial_backoff_seconds=initial_backoff_seconds,
            max_backoff_seconds=max_backoff_seconds,
        )


__all__ = ["ConfigSyncProvider"]
