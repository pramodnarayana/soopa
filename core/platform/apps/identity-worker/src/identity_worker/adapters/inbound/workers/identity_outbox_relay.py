import asyncio
import contextlib
from typing import Any

import asyncpg
import structlog
from sqlalchemy.engine import make_url

from identity_worker.application.use_cases.identity_outbox_processor_use_case import (
    IdentityOutboxProcessorUseCase,
)

logger = structlog.get_logger(__name__)


class IdentityOutboxRelay:
    """
    Inbound adapter that listens to Postgres NOTIFY events and triggers
    the application service (IdentityOutboxProcessorUseCase).
    """

    def __init__(
        self,
        processor: IdentityOutboxProcessorUseCase,
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
            logger.info("identity_postgres_outbox_listener_started")

    async def stop(self) -> None:
        self.is_running = False
        self._notify_event.set()
        self.processor.stop()

        if self._connection:
            try:
                await self._connection.remove_listener("identity_outbox_wakeup", self._on_notify)
                await self._connection.close()
            except (asyncpg.PostgresError, OSError, ConnectionError) as e:
                logger.warning("identity_outbox_listener_connection_close_error", error=str(e))

        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            logger.info("identity_postgres_outbox_listener_stopped")

    def _on_notify(
        self, connection: asyncpg.Connection, pid: int, channel: str, payload: str
    ) -> None:
        logger.debug("identity_instant_wakeup_received", channel=channel, pid=pid)
        self._notify_event.set()

    async def _setup_listener(self) -> None:
        if not self.database_url:
            return
        try:
            url = make_url(self.database_url).set(drivername="postgresql")
            asyncpg_url = url.render_as_string(hide_password=False)

            self._connection = await asyncpg.connect(asyncpg_url)
            await self._connection.add_listener("identity_outbox_wakeup", self._on_notify)
            logger.info("identity_outbox_listener_listening", channel="identity_outbox_wakeup")
        except Exception:
            if self._connection:
                await self._connection.close()
                self._connection = None
            logger.exception("identity_outbox_listener_connection_failed")

    async def _process_loop_iteration(self) -> None:
        if self._connection and self._connection.is_closed():
            logger.warning("asyncpg_connection_lost", action="reconnecting")
            self._connection = None

        if not self._connection:
            await self._setup_listener()
            if not self._connection:
                await asyncio.sleep(5.0)
                return

        # Clear event before processing to capture notifications during drain
        if self.is_running:
            self._notify_event.clear()

        # Process pending until empty
        more_events = True
        while more_events and self.is_running:
            more_events = await self.processor.process_pending()

        if self.is_running:
            with contextlib.suppress(asyncio.TimeoutError, TimeoutError):
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
                    logger.exception("identity_outbox_relay_error")
                    await asyncio.sleep(5.0)

        with contextlib.suppress(asyncio.CancelledError):
            await _listen()
