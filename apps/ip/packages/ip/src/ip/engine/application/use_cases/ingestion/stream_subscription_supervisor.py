"""Supervisor managing persistent streaming subscription runners in compliance with physical worker isolation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping

import structlog

from ip.engine.application.use_cases.ingestion.ingest_stream_batch_use_case import (
    IngestStreamBatchCommand,
    IngestStreamBatchUseCase,
)
from ip.engine.domain.enums import AckVerdict
from ip.engine.domain.models.stream_definition import StreamDefinition
from ip.engine.ports.outbound.subscribe_transport_port import (
    RawMessageBatchDTO,
    SubscribeTransportPort,
)

logger = structlog.get_logger(__name__)


class StreamSubscriptionSupervisor:
    """Manages active, supervised streaming subscription tasks.

    Runs strictly inside the dedicated worker container (`ip-stream-worker`), completely
    isolated from the HTTP API container.
    """

    def __init__(
        self,
        ingest_use_case: IngestStreamBatchUseCase | Callable[[], IngestStreamBatchUseCase],
        transports: Mapping[str, SubscribeTransportPort],
        max_restart_attempts: int = 5,
        base_backoff_seconds: float = 0.2,
    ) -> None:
        self._ingest_use_case = ingest_use_case
        self._transports = dict(transports)
        self._max_restart_attempts = max_restart_attempts
        self._base_backoff_seconds = base_backoff_seconds
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._stop_events: dict[str, asyncio.Event] = {}

    @property
    def active_subscription_keys(self) -> list[str]:
        """Returns the list of active subscription composite keys (connection_id:stream)."""
        return [k for k, t in self._tasks.items() if not t.done()]

    def start_subscription(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        app_id: str,
        stream: StreamDefinition,
    ) -> None:
        """Starts a supervised consumer task for an active streaming connection and stream."""
        sub_key = f"{connection_id}:{stream.stream}"
        if sub_key in self._tasks and not self._tasks[sub_key].done():
            logger.info(
                "stream_subscription_already_running",
                connection_id=connection_id,
                stream=stream.stream,
            )
            return

        transport = self._transports.get(connection_id)
        if transport is None:
            logger.error(
                "stream_subscription_transport_missing",
                connection_id=connection_id,
                stream=stream.stream,
            )
            return

        stop_event = asyncio.Event()
        self._stop_events[sub_key] = stop_event

        async def _message_handler(batch: RawMessageBatchDTO) -> AckVerdict:
            cmd = IngestStreamBatchCommand(
                tenant_id=tenant_id,
                connection_id=connection_id,
                app_id=app_id,
                stream_name=stream.stream,
                batch=batch,
            )
            use_case = (
                self._ingest_use_case()
                if callable(self._ingest_use_case)
                else self._ingest_use_case
            )
            res = await use_case.execute(cmd)
            return res.verdict

        async def _runner() -> None:
            logger.info(
                "stream_subscription_started",
                connection_id=connection_id,
                stream=stream.stream,
                tenant_id=tenant_id,
            )
            attempt = 0
            try:
                while not stop_event.is_set():
                    try:
                        await transport.start_consumer(
                            stream=stream,
                            message_handler=_message_handler,
                            stop_signal=stop_event,
                        )
                        break
                    except asyncio.CancelledError:
                        logger.info(
                            "stream_subscription_cancelled",
                            connection_id=connection_id,
                            stream=stream.stream,
                        )
                        break
                    except Exception as exc:
                        attempt += 1
                        logger.exception(
                            "stream_subscription_runner_error",
                            connection_id=connection_id,
                            stream=stream.stream,
                            attempt=attempt,
                            error=str(exc),
                        )
                        if attempt >= self._max_restart_attempts or stop_event.is_set():
                            break
                        backoff = min(self._base_backoff_seconds * (2 ** (attempt - 1)), 30.0)
                        await asyncio.sleep(backoff)
            finally:
                logger.info(
                    "stream_subscription_stopped",
                    connection_id=connection_id,
                    stream=stream.stream,
                )

        self._tasks[sub_key] = asyncio.create_task(_runner())

    async def stop_subscription(self, connection_id: str, stream_name: str) -> None:
        """Stops a specific active subscription runner."""
        sub_key = f"{connection_id}:{stream_name}"
        stop_event = self._stop_events.get(sub_key)
        if stop_event is not None:
            stop_event.set()

        task = self._tasks.get(sub_key)
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
            except TimeoutError:
                task.cancel()

    async def stop_all(self) -> None:
        """Gracefully shuts down all active streaming subscriptions."""
        logger.info("stream_subscription_supervisor_stopping_all")
        for stop_event in self._stop_events.values():
            stop_event.set()

        running_tasks = [t for t in self._tasks.values() if not t.done()]
        if running_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*running_tasks, return_exceptions=True),
                    timeout=5.0,
                )
            except TimeoutError:
                for t in running_tasks:
                    if not t.done():
                        t.cancel()
        logger.info("stream_subscription_supervisor_stopped_all")
