import asyncio
import contextlib
import json
import logging
import re
from typing import Any

import asyncpg

from notification.application.ports.notification_query_port import NotificationDTO
from notification.application.ports.notification_stream_port import NotificationStreamPort

logger = logging.getLogger(__name__)


class PostgresNotificationListener:
    """
    Listens to Postgres NOTIFY events on the 'in_app_notifications' channel
    and bridges them to the NotificationStreamManager for SSE streaming.
    """

    def __init__(
        self,
        database_url: str,
        stream_manager: NotificationStreamPort,
        channel: str = "in_app_notifications",
    ):
        self.database_url = re.sub(r"^postgresql\+[^:]+://", "postgresql://", database_url)
        self.channel = channel
        self.stream_manager = stream_manager
        self.is_running = False
        self._connection: asyncpg.Connection | None = None
        self._task: asyncio.Task[Any] | None = None
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._ready = asyncio.Event()

    def start(self) -> None:
        if not self.is_running:
            self.is_running = True
            self._ready.clear()
            self._task = asyncio.create_task(self._run_loop())
            logger.info(f"Started PostgresNotificationListener on channel '{self.channel}'")

    async def wait_until_ready(self, timeout: float = 5.0) -> None:
        """Wait until the listener is connected and ready to receive notifications."""
        await asyncio.wait_for(self._ready.wait(), timeout=timeout)

    async def stop(self) -> None:
        self.is_running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info(f"Stopped PostgresNotificationListener on channel '{self.channel}'")

    async def _run_loop(self) -> None:
        while self.is_running:
            try:
                logger.debug(f"Connecting to database to listen on '{self.channel}'...")
                self._connection = await asyncpg.connect(self.database_url)
                await self._connection.add_listener(self.channel, self._on_notify)
                logger.info(f"Listening on Postgres channel '{self.channel}'")

                # Signal that listener is ready
                self._ready.set()

                # Keep connection alive while running
                while self.is_running and not self._connection.is_closed():
                    await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in PostgresNotificationListener connection loop")
            finally:
                # Clean up existing connection before reconnecting
                if self._connection:
                    try:
                        await self._connection.remove_listener(self.channel, self._on_notify)
                        await self._connection.close()
                    except Exception:
                        logger.exception("Error closing connection during cleanup")
                    finally:
                        self._connection = None
                if self.is_running:
                    await asyncio.sleep(5)  # Backoff before reconnecting

    def _on_notify(
        self, connection: asyncpg.Connection, pid: int, channel: str, payload: str
    ) -> None:
        """Callback invoked by asyncpg when a NOTIFY is received."""
        try:
            event_data = json.loads(payload)
            tenant_id = event_data.get("tenant_id")
            user_id = event_data.get("user_id")
            notification_id = event_data.get("id")
            title = event_data.get("title")
            body = event_data.get("body")

            if not tenant_id or not user_id or not notification_id or not title or not body:
                logger.warning(
                    f"Received malformed notification event (missing required fields): {payload}"
                )
                return

            notification = NotificationDTO(
                id=notification_id,
                title=title,
                body=body,
                severity=event_data.get("severity", "info"),
                is_read=event_data.get("is_read", False),
                created_at=event_data.get("created_at"),
            )

            # Fire and forget the broadcast
            task = asyncio.create_task(
                self.stream_manager.broadcast(tenant_id, user_id, notification)
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        except Exception:
            logger.exception("Failed to process Postgres NOTIFY payload")
