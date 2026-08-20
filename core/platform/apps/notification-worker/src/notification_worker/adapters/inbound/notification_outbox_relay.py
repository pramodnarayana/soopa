import asyncio
from typing import Any

import asyncpg
import structlog
from notification.application.notification_outbox_processor_use_case import (
    NotificationOutboxProcessorUseCase,
)

logger = structlog.get_logger(__name__)


class NotificationOutboxRelay:
    """
    Inbound adapter that listens to Postgres NOTIFY events and triggers
    the application service (NotificationOutboxProcessor).
    """

    def __init__(
        self,
        processor: NotificationOutboxProcessorUseCase,
        database_url: str,
        fallback_poll_interval: int = 60,
    ):
        self.processor = processor
        self.database_url = database_url
        self.fallback_poll_interval = fallback_poll_interval
        self.is_running = False
        self._notify_event = asyncio.Event()

    def start(self) -> asyncio.Task[Any]:
        self.is_running = True
        return asyncio.create_task(self._run_loop())

    def stop(self) -> None:
        self.is_running = False
        self._notify_event.set()
        self.processor.stop()

    def _handle_notification(
        self, connection: asyncpg.Connection, pid: int, channel: str, payload: Any
    ) -> None:
        logger.debug("Received postgres notification", channel=channel, payload=payload)
        self._notify_event.set()

    async def _run_loop(self) -> None:
        logger.info(
            "Starting Postgres Outbox Listener",
            channel="notification_outbox_channel",
        )

        while self.is_running:
            conn = None
            try:
                conn = await asyncpg.connect(
                    self.database_url.replace("postgresql+asyncpg://", "postgresql://")
                )
                await conn.add_listener("notification_outbox_channel", self._handle_notification)
                logger.info("Connected and listening on notification_outbox_channel")

                while self.is_running:
                    # Clear event before processing to capture any notifications during drain
                    self._notify_event.clear()

                    # Drain of any existing messages
                    await self.processor.process_pending()

                    import contextlib

                    with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
                        # Wait for a notification OR the fallback interval
                        await asyncio.wait_for(
                            self._notify_event.wait(), timeout=self.fallback_poll_interval
                        )

            except Exception:
                logger.exception("Error in Postgres Outbox Listener loop. Reconnecting in 5s...")
                await asyncio.sleep(5.0)
            finally:
                if conn:
                    await conn.remove_listener(
                        "notification_outbox_channel", self._handle_notification
                    )
                    await conn.close()

        logger.info("Postgres Outbox Listener stopped.")
