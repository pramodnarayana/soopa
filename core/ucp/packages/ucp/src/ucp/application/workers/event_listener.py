import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


class ControlPlaneEventListener:
    """
    Listens to Postgres NOTIFY events on the 'control_plane_events' channel.
    This acts as our local/dev async event bus without needing SQS/Kafka.
    """

    def __init__(
        self,
        database_url: str,
        channel: str = "control_plane_events",
    ):
        self.database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
        self.channel = channel
        self._handlers: dict[str, list[Callable[[dict[str, Any]], Any]]] = {}
        self.is_running = False
        self._connection: asyncpg.Connection | None = None
        self._task: asyncio.Task[Any] | None = None
        self._background_tasks: set[asyncio.Task[Any]] = set()

    def subscribe(self, event_type: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        """Register a handler for a specific event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def start(self) -> None:
        if not self.is_running:
            self.is_running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info(f"Started ControlPlaneEventListener on channel '{self.channel}'")

    async def stop(self) -> None:
        self.is_running = False
        if self._connection:
            try:
                await self._connection.remove_listener(self.channel, self._on_notify)
                await self._connection.close()
            # Exception catch is broad because this is part of the final shutdown teardown
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Error closing listener connection: {e}")
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info(f"Stopped ControlPlaneEventListener on channel '{self.channel}'")

    async def _run_loop(self) -> None:
        while self.is_running:
            try:
                logger.debug(f"Connecting to database to listen on '{self.channel}'...")
                self._connection = await asyncpg.connect(self.database_url)
                await self._connection.add_listener(self.channel, self._on_notify)
                logger.info(f"Listening on Postgres channel '{self.channel}'")

                # Keep connection alive while running
                while self.is_running and not self._connection.is_closed():
                    await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in ControlPlaneEventListener connection loop")
                if self.is_running:
                    await asyncio.sleep(5)  # Backoff before reconnecting

    def _on_notify(
        self, connection: asyncpg.Connection, pid: int, channel: str, payload: str
    ) -> None:
        """Callback invoked by asyncpg when a NOTIFY is received."""
        try:
            event_data = json.loads(payload)
            event_type = event_data.get("eventType")
            if not event_type:
                logger.warning(f"Received malformed event (no eventType): {payload}")
                return

            handlers = self._handlers.get(event_type, [])
            if not handlers:
                logger.debug(f"No handlers registered for event type: {event_type}")
                return

            # Execute handlers asynchronously
            for handler in handlers:
                task = asyncio.create_task(self._execute_handler(handler, event_data))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)

        except Exception:
            logger.exception("Failed to process Postgres NOTIFY payload")

    async def _execute_handler(
        self, handler: Callable[[dict[str, Any]], Any], event_data: dict[str, Any]
    ) -> None:
        try:
            if asyncio.iscoroutinefunction(handler):
                await handler(event_data)
            else:
                handler(event_data)
        except Exception:
            logger.exception(f"Handler {handler.__name__} failed processing event")
