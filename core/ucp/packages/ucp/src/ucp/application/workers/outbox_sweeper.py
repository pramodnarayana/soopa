import asyncio
import contextlib
import uuid
from typing import Any

import asyncpg
import structlog

from ...domain.models.outbox_event import OutboxEvent
from ...ports.outbox_publisher import OutboxPublisherPort
from ...ports.outbox_repository import OutboxRepositoryPort

logger = structlog.get_logger(__name__)


class ControlPlaneOutboxSweeper:
    def __init__(
        self,
        repository: OutboxRepositoryPort,
        publisher: OutboxPublisherPort,
        database_url: str,
        poll_interval_seconds: int = 5,
        max_concurrent_events: int = 50,
        lock_lease_ms: int = 30000,
        worker_id: str | None = None,
    ):
        self.repository = repository
        self.publisher = publisher
        self.database_url = database_url
        self.worker_id = worker_id or str(uuid.uuid4())
        self.poll_interval_seconds = poll_interval_seconds
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
            logger.info("outbox_sweeper_started", worker_id=self.worker_id)

    async def stop(self) -> None:
        self.is_running = False
        self._poll_event.set()  # Wake up the polling loop to exit
        if self._connection:
            try:
                await self._connection.remove_listener("ucp_outbox_wakeup", self._on_notify)
                await self._connection.close()
            except Exception as e:  # noqa: BLE001
                logger.warning("outbox_sweeper_connection_close_error", error=str(e))

        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            logger.info("outbox_sweeper_stopped", worker_id=self.worker_id)

    def _on_notify(
        self, connection: asyncpg.Connection, pid: int, channel: str, payload: str
    ) -> None:
        """Called instantly when Postgres trigger fires pg_notify."""
        logger.debug("instant_wakeup_received", channel=channel, pid=pid)
        self._poll_event.set()

    async def _setup_listener(self) -> None:
        """Sets up the Postgres NOTIFY listener for instant wakeups (Outbox Relay pattern)."""
        if not self.database_url:
            return
        try:
            self._connection = await asyncpg.connect(self.database_url)
            await self._connection.add_listener("ucp_outbox_wakeup", self._on_notify)
            logger.info("outbox_relay_listening", channel="ucp_outbox_wakeup")
        except Exception:
            logger.exception("outbox_relay_connection_failed", fallback="pure_polling")

    async def _run_loop(self) -> None:
        await self._setup_listener()

        async def _sweep() -> None:
            while self.is_running:
                # Check connection health and reconnect if necessary
                if self._connection and self._connection.is_closed():
                    logger.warning("asyncpg_connection_lost", action="reconnecting")
                    self._connection = None
                    await self._setup_listener()

                try:
                    await self.poll()
                except asyncio.CancelledError:
                    break
                except Exception:
                    logger.exception("outbox_sweeper_poll_loop_error")

                if self.is_running:
                    # Wait for EITHER the timer OR an instant wakeup from Postgres
                    self._poll_event.clear()
                    import contextlib

                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(
                            self._poll_event.wait(), timeout=self.poll_interval_seconds
                        )

        try:
            if hasattr(self.publisher, "__aenter__"):
                async with self.publisher:  # type: ignore
                    await _sweep()
            else:
                await _sweep()
        except asyncio.CancelledError:
            pass

    async def poll(self) -> None:
        # 1. Sweep stuck events
        swept = await self.repository.sweep_stuck_events(self.lock_lease_ms)
        if swept > 0:
            logger.info("stuck_events_swept", count=swept, target_status="PENDING")

        # 2. Claim next events using SKIP LOCKED
        events = await self.repository.claim_next_events(
            worker_id=self.worker_id,
            limit=self.max_concurrent_events,
            lock_lease_ms=self.lock_lease_ms,
        )

        if events:
            logger.debug("events_claimed", worker_id=self.worker_id, count=len(events))

            # 3. Execute concurrently
            tasks = [self.process_event(event) for event in events]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def process_event(self, event: OutboxEvent) -> None:
        try:
            await self.publisher.publish(event)
            await self.repository.mark_completed(event.id, self.worker_id)
            logger.debug("outbox_event_processed", event_id=event.id, event_type=event.event_type)
        except Exception as e:
            logger.exception(
                "outbox_event_processing_failed",
                event_id=event.id,
                event_type=event.event_type,
            )
            await self.repository.mark_failed(event.id, self.worker_id, str(e))
