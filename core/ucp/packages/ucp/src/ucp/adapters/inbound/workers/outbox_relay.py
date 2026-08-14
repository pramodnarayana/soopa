import asyncio
import contextlib
import uuid
from typing import Any

import asyncpg
import structlog
from sqlalchemy.engine import make_url

from ucp.domain.models.outbox_event import OutboxEvent
from ucp.ports.outbox_publisher import OutboxPublisherPort
from ucp.ports.outbox_repository import OutboxRepositoryPort

logger = structlog.get_logger(__name__)


class ControlPlaneOutboxRelay:
    """
    Real-time Relay worker that listens for PostgreSQL LISTEN/NOTIFY events
    and immediately publishes pending outbox events.
    """

    def __init__(
        self,
        repository: OutboxRepositoryPort,
        publisher: OutboxPublisherPort,
        database_url: str,
        max_concurrent_events: int = 50,
        lock_lease_ms: int = 30000,
        worker_id: str | None = None,
    ):
        self.repository = repository
        self.publisher = publisher
        self.database_url = database_url
        self.worker_id = worker_id or str(uuid.uuid4())
        self.max_concurrent_events = max_concurrent_events
        self.lock_lease_ms = lock_lease_ms
        self.is_running = False
        self._task: asyncio.Task[Any] | None = None
        self._poll_event = asyncio.Event()
        self._connection: asyncpg.Connection | None = None

    def start(self) -> None:
        if not self.is_running:
            self.is_running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info("outbox_relay_started", worker_id=self.worker_id)

    async def stop(self) -> None:
        self.is_running = False
        self._poll_event.set()  # Wake up the loop to exit
        if self._connection:
            try:
                await self._connection.remove_listener("ucp_outbox_wakeup", self._on_notify)
                await self._connection.close()
            except Exception as e:  # noqa: BLE001
                logger.warning("outbox_relay_connection_close_error", error=str(e))

        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            logger.info("outbox_relay_stopped", worker_id=self.worker_id)

    def _on_notify(
        self, connection: asyncpg.Connection, pid: int, channel: str, payload: str
    ) -> None:
        """Called instantly when Postgres trigger fires pg_notify."""
        logger.debug("instant_wakeup_received", channel=channel, pid=pid)
        self._poll_event.set()

    async def _setup_listener(self) -> None:
        if not self.database_url:
            return
        try:
            url = make_url(self.database_url).set(drivername="postgresql")
            asyncpg_url = url.render_as_string(hide_password=False)
            self._connection = await asyncpg.connect(asyncpg_url)
            await self._connection.add_listener("ucp_outbox_wakeup", self._on_notify)
            logger.info("outbox_relay_listening", channel="ucp_outbox_wakeup")
        except Exception:
            if self._connection:
                await self._connection.close()
                self._connection = None
            logger.exception("outbox_relay_connection_failed")

    async def _run_loop(self) -> None:
        await self._setup_listener()

        async def _relay() -> None:
            while self.is_running:
                if self._connection and self._connection.is_closed():
                    logger.warning("asyncpg_connection_lost", action="reconnecting")
                    self._connection = None
                    await self._setup_listener()

                try:
                    await self.poll()
                except asyncio.CancelledError:
                    break
                except Exception:
                    logger.exception("outbox_relay_poll_error")

                if self.is_running:
                    self._poll_event.clear()
                    await self._poll_event.wait()

        try:
            if hasattr(self.publisher, "__aenter__"):
                async with self.publisher:  # type: ignore
                    await _relay()
            else:
                await _relay()
        except asyncio.CancelledError:
            pass

    async def poll(self) -> None:
        events = await self.repository.claim_next_events(
            worker_id=self.worker_id,
            limit=self.max_concurrent_events,
            lock_lease_ms=self.lock_lease_ms,
        )

        if events:
            logger.debug("relay_events_claimed", worker_id=self.worker_id, count=len(events))
            tasks = [self.process_event(event) for event in events]
            await asyncio.gather(*tasks, return_exceptions=True)

            # If we maxed out the batch, there might be more events waiting
            if len(events) >= self.max_concurrent_events:
                self._poll_event.set()

    async def process_event(self, event: OutboxEvent) -> None:
        try:
            await self.publisher.publish(event)
            await self.repository.mark_completed(event.id, self.worker_id)
            logger.debug(
                "outbox_event_processed_by_relay", event_id=event.id, event_type=event.event_type
            )
        except Exception as e:
            logger.exception(
                "outbox_event_processing_failed_by_relay",
                event_id=event.id,
                event_type=event.event_type,
            )
            await self.repository.mark_failed(event.id, self.worker_id, str(e))
