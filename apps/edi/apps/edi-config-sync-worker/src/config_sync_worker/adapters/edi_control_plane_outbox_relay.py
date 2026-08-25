import asyncio
import contextlib
from typing import Any

import asyncpg
import structlog
from sqlalchemy.engine import make_url

from config_sync_worker.provision.edi_control_plane_outbox_processor_use_case import (
    EdiControlPlaneOutboxProcessorUseCase,
)

logger = structlog.get_logger(__name__)


class EdiControlPlaneOutboxRelay:
    """
    Inbound adapter that listens to Postgres NOTIFY events and triggers
    the application service (PublishEdiOutboxUseCase).
    """

    def __init__(
        self,
        processor: EdiControlPlaneOutboxProcessorUseCase,
        database_url: str,
        fallback_poll_interval: int = 60,
    ):
        self.processor = processor
        self.database_url = database_url
        self.fallback_poll_interval = fallback_poll_interval
        self.is_running = False
        self._task: asyncio.Task[Any] | None = None
        self._notify_event = asyncio.Event()
        self._connection: asyncpg.Connection | None = None

    def start(self) -> None:
        if not self.is_running:
            self.is_running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info("edi_postgres_outbox_listener_started")

    async def stop(self) -> None:
        self.is_running = False
        self._notify_event.set()
        self.processor.stop()

        if self._connection:
            try:
                await self._connection.remove_listener("edi_outbox_channel", self._on_notify)
                await self._connection.close()
            except (asyncpg.PostgresError, OSError, ConnectionError) as e:
                logger.warning("edi_outbox_listener_connection_close_error", error=str(e))

        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            logger.info("edi_postgres_outbox_listener_stopped")

    def _on_notify(
        self, connection: asyncpg.Connection, pid: int, channel: str, payload: str
    ) -> None:
        logger.debug("edi_instant_wakeup_received", channel=channel, pid=pid)
        self._notify_event.set()

    async def _setup_listener(self) -> None:
        if not self.database_url:
            return
        try:
            url = make_url(self.database_url).set(drivername="postgresql")
            asyncpg_url = url.render_as_string(hide_password=False)

            self._connection = await asyncpg.connect(asyncpg_url)
            await self._connection.add_listener("edi_outbox_channel", self._on_notify)
            logger.info("edi_outbox_listener_listening", channel="edi_outbox_channel")
        except Exception:
            if self._connection:
                await self._connection.close()
                self._connection = None
            logger.exception("edi_outbox_listener_connection_failed")

    async def _run_loop(self) -> None:
        await self._setup_listener()

        base_delay = 1.0
        max_delay = 60.0
        current_delay = base_delay

        async def _listen() -> None:
            nonlocal current_delay
            while self.is_running:
                if self._connection and self._connection.is_closed():
                    logger.warning("asyncpg_connection_lost", action="reconnecting")
                    self._connection = None

                if not self._connection:
                    await self._setup_listener()
                    if not self._connection:
                        logger.warning("edi_outbox_listener_reconnect_failed", delay=current_delay)
                        await asyncio.sleep(current_delay)
                        current_delay = min(current_delay * 2, max_delay)
                        continue

                    # Reset backoff on successful connection
                    current_delay = base_delay

                # Process pending until empty
                more_events = True
                while more_events and self.is_running:
                    try:
                        more_events = await self.processor.process_pending()
                        current_delay = base_delay
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.exception("edi_outbox_processor_failed", error=str(e))
                        await asyncio.sleep(current_delay)
                        current_delay = min(current_delay * 2, max_delay)
                        more_events = False

                if self.is_running:
                    self._notify_event.clear()
                    with contextlib.suppress(asyncio.TimeoutError, TimeoutError):
                        await asyncio.wait_for(
                            self._notify_event.wait(), timeout=self.fallback_poll_interval
                        )

        with contextlib.suppress(asyncio.CancelledError):
            await _listen()
