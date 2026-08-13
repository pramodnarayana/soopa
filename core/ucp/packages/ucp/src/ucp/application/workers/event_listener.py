import asyncio
import contextlib
import json
from collections.abc import Callable
from typing import Any

import asyncpg
import structlog
from sqlalchemy.engine import make_url

logger = structlog.get_logger(__name__)


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
        self.database_url = database_url
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
            logger.info("control_plane_event_listener_started", channel=self.channel)

    async def stop(self) -> None:
        self.is_running = False
        if self._connection:
            try:
                await self._connection.remove_listener(self.channel, self._on_notify)
                await self._connection.close()
            # Exception catch is broad because this is part of the final shutdown teardown
            except Exception as e:  # noqa: BLE001
                logger.warning("error_closing_listener_connection", error=str(e))
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

        if self._background_tasks:
            for task in list(self._background_tasks):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            self._background_tasks.clear()

        logger.info("control_plane_event_listener_stopped", channel=self.channel)

    async def _run_loop(self) -> None:
        while self.is_running:
            try:
                url = make_url(self.database_url).set(drivername="postgresql")
                asyncpg_url = url.render_as_string(hide_password=False)
                self._connection = await asyncpg.connect(asyncpg_url)
                logger.info("event_listener_connected")
                await self._connection.add_listener(self.channel, self._on_notify)
                logger.info("listening_on_postgres_channel", channel=self.channel)

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
                logger.warning("received_malformed_event_no_event_type")
                return

            handlers = self._handlers.get(event_type, [])
            if not handlers:
                logger.debug("no_handlers_registered_for_event_type", event_type=event_type)
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
            logger.exception("handler_failed_processing_event", handler_name=handler.__name__)
