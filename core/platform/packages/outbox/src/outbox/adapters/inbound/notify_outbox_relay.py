"""Inbound LISTEN/NOTIFY Outbox Relay Adapter."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

import structlog
from database.listener import NotifyListenerConnectionPort
from database.provider import DatabaseProvider
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase
from outbox.ports.outbox_relay_port import OutboxRelayPort

logger = structlog.get_logger(__name__)

ListenerConnector = Callable[[str], Awaitable[NotifyListenerConnectionPort]]


class NotifyOutboxRelay(OutboxRelayPort):
    """
    Inbound adapter that listens to database NOTIFY wakeup events via
    `DatabaseProvider.connect_listener` and triggers `OutboxProcessorUseCase`.
    """

    def __init__(
        self,
        processor: OutboxProcessorUseCase,
        database_url: str,
        listen_channel: str,
        fallback_poll_interval: int = 60,
        listener_connector: ListenerConnector = DatabaseProvider.connect_listener,
    ) -> None:
        self.processor = processor
        self.database_url = database_url
        self.listen_channel = listen_channel
        self.fallback_poll_interval = fallback_poll_interval
        self._listener_connector = listener_connector
        self.is_running = False
        self._task: asyncio.Task[object] | None = None
        self._notify_event = asyncio.Event()
        self._connection: NotifyListenerConnectionPort | None = None

    def background_tasks(self) -> list[asyncio.Task[object]]:
        return [self._task] if self._task else []

    def start(self) -> None:
        if not self.is_running:
            self.is_running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info("notify_outbox_listener_started", channel=self.listen_channel)

    async def stop(self) -> None:
        self.is_running = False
        self._notify_event.set()
        self.processor.stop()

        if self._connection:
            try:
                await self._connection.remove_listener(self.listen_channel, self._on_notify)
                await self._connection.close()
            except Exception:
                logger.exception("outbox_listener_connection_close_failed")
            finally:
                self._connection = None

        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            logger.info("notify_outbox_listener_stopped", channel=self.listen_channel)

    def _on_notify(self, connection: object, pid: int, channel: str, payload: str) -> None:
        del connection, payload
        logger.debug("instant_wakeup_received", channel=channel, pid=pid)
        self._notify_event.set()

    async def _setup_listener(self) -> None:
        if not self.database_url:
            return
        try:
            self._connection = await self._listener_connector(self.database_url)
            await self._connection.add_listener(self.listen_channel, self._on_notify)
            logger.info("outbox_listener_listening", channel=self.listen_channel)
        except Exception:
            if self._connection:
                with contextlib.suppress(Exception):
                    await self._connection.close()
                self._connection = None
            logger.exception("outbox_listener_connection_failed")

    async def _process_loop_iteration(self) -> None:
        if self._connection and self._connection.is_closed():
            logger.warning("notify_listener_connection_lost", action="reconnecting")
            self._connection = None

        if not self._connection:
            await self._setup_listener()
            if not self._connection:
                await asyncio.sleep(5.0)
                return

        if self.is_running:
            self._notify_event.clear()

        more_events = True
        while more_events and self.is_running:
            more_events = await self.processor.process_pending()

        if self.is_running:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._notify_event.wait(), timeout=self.fallback_poll_interval
                )

    async def _run_loop(self) -> None:
        await self._setup_listener()

        async def _listen() -> None:
            while self.is_running:
                try:
                    await self._process_loop_iteration()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("notify_outbox_relay_error")
                    await asyncio.sleep(5.0)

        with contextlib.suppress(asyncio.CancelledError):
            await _listen()


__all__ = ["ListenerConnector", "NotifyOutboxRelay"]
