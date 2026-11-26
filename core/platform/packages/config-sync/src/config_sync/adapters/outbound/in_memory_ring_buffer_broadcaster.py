"""In-memory cyclic Ring Buffer and bounded fan-out SSE Broadcaster implementing ConfigBroadcasterPort."""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog

from config_sync.domain.dtos import ConfigCursor, ConfigDeltaEvent
from config_sync.ports.config_broadcaster_port import ConfigBroadcasterPort

logger = structlog.get_logger(__name__)

_StreamKey = tuple[str, str]  # (app_id, tenant_id)
_END_OF_STREAM = object()


class InMemoryRingBufferBroadcaster(ConfigBroadcasterPort):
    """Per-(app, tenant) cyclic ring buffer + bounded asyncio.Queue broadcaster for live SSE streams."""

    def __init__(
        self,
        *,
        ring_buffer_size: int = 1000,
        subscriber_queue_maxsize: int = 256,
        broadcast_tenant_ids: tuple[str, ...] = (),
    ) -> None:
        if ring_buffer_size <= 0:
            raise ValueError("ring_buffer_size must be strictly positive")
        if subscriber_queue_maxsize <= 0:
            raise ValueError("subscriber_queue_maxsize must be strictly positive")
        self._ring_buffer_size = ring_buffer_size
        self._subscriber_queue_maxsize = subscriber_queue_maxsize
        self._broadcast_tenant_ids = frozenset(broadcast_tenant_ids)
        self._buffers: dict[_StreamKey, deque[ConfigDeltaEvent]] = {}
        self._evicted_before: dict[_StreamKey, ConfigCursor] = defaultdict(ConfigCursor.zero)
        self._subscribers: dict[_StreamKey, set[asyncio.Queue[ConfigDeltaEvent | object]]] = (
            defaultdict(set)
        )

    def _append_to_buffer(self, key: _StreamKey, event: ConfigDeltaEvent) -> None:
        buf = self._buffers.get(key)
        if buf is None:
            buf = deque(maxlen=self._ring_buffer_size)
            self._buffers[key] = buf
        if len(buf) == self._ring_buffer_size:
            evicted = buf[0]
            self._evicted_before[key] = max(self._evicted_before[key], evicted.cursor)
        buf.append(event)

    def _enqueue_subscriber(
        self,
        key: _StreamKey,
        queue: asyncio.Queue[ConfigDeltaEvent | object],
        event: ConfigDeltaEvent,
    ) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            # Slow consumer: close its stream cleanly so it reconnects & self-heals via snapshot.
            logger.error(
                "config_watch_slow_subscriber_evicted",
                app_id=key[0],
                tenant_id=key[1],
                dropped_version=event.version,
                dropped_txid=event.txid,
            )
            self._subscribers[key].discard(queue)
            with contextlib.suppress(asyncio.QueueEmpty):
                queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(_END_OF_STREAM)

    async def publish_delta(self, event: ConfigDeltaEvent) -> None:
        app_id = event.app_id
        tenant_id = event.tenant_id
        is_broadcast = tenant_id in self._broadcast_tenant_ids

        # Always store the delta in its canonical source key buffer so disconnected tenants
        # never lose shared/broadcast deltas when reconnecting (`get_buffered_deltas_since`
        # merges both tenant and broadcast buffers or falls back to PostgreSQL).
        canonical_key: _StreamKey = (app_id, tenant_id)
        self._append_to_buffer(canonical_key, event)

        target_keys: list[_StreamKey]
        if is_broadcast:
            active_keys = [k for k in self._subscribers if k[0] == app_id]
            target_keys = list({*active_keys, canonical_key})
        else:
            target_keys = [canonical_key]

        for key in target_keys:
            if key != canonical_key:
                self._append_to_buffer(key, event)
            for subscriber_q in list(self._subscribers.get(key, ())):
                self._enqueue_subscriber(key, subscriber_q, event)

    def _collect_buffer_since(
        self,
        key: _StreamKey,
        since_cursor: ConfigCursor,
        *,
        require_present: bool,
    ) -> list[ConfigDeltaEvent] | None:
        if self._evicted_before.get(key, ConfigCursor.zero()) >= since_cursor:
            return None
        buf = self._buffers.get(key)
        if not buf:
            return None if require_present else []
        if since_cursor < buf[0].cursor:
            return None
        return [evt for evt in buf if evt.cursor > since_cursor]

    def get_buffered_deltas_since(
        self,
        *,
        app_id: str,
        tenant_id: str,
        since_cursor: ConfigCursor,
    ) -> list[ConfigDeltaEvent] | None:
        """Returns complete merged tenant + broadcast deltas after `since_cursor`, or `None` for DB catch-up."""
        if since_cursor.is_zero:
            return None

        tenant_events = self._collect_buffer_since(
            (app_id, tenant_id),
            since_cursor,
            require_present=True,
        )
        if tenant_events is None:
            return None

        merged: dict[ConfigCursor, ConfigDeltaEvent] = {evt.cursor: evt for evt in tenant_events}
        for shared_tid in self._broadcast_tenant_ids:
            if shared_tid == tenant_id:
                continue
            shared_events = self._collect_buffer_since(
                (app_id, shared_tid),
                since_cursor,
                require_present=False,
            )
            if shared_events is None:
                return None
            for evt in shared_events:
                merged[evt.cursor] = evt

        return [merged[cur] for cur in sorted(merged)]

    @asynccontextmanager
    async def subscribe(
        self,
        *,
        app_id: str,
        tenant_id: str,
    ) -> AsyncIterator[AsyncIterator[ConfigDeltaEvent]]:
        key: _StreamKey = (app_id, tenant_id)
        queue: asyncio.Queue[ConfigDeltaEvent | object] = asyncio.Queue(
            maxsize=self._subscriber_queue_maxsize
        )
        self._subscribers[key].add(queue)

        async def _iter() -> AsyncIterator[ConfigDeltaEvent]:
            while True:
                item = await queue.get()
                if item is _END_OF_STREAM:
                    break
                if isinstance(item, ConfigDeltaEvent):
                    yield item

        try:
            yield _iter()
        finally:
            self._subscribers[key].discard(queue)
            if not self._subscribers[key]:
                self._subscribers.pop(key, None)


__all__ = ["InMemoryRingBufferBroadcaster"]
