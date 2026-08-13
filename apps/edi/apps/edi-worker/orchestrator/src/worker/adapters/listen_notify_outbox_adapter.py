import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import structlog
from sqlalchemy.engine import make_url

from worker.adapters.acl.registry import translate_external_event
from worker.ports.outbox import OutboxEvent, OutboxPort

logger = structlog.get_logger(__name__)


class PostgresOutboxEvent(OutboxEvent):
    def __init__(self, message_id: str, body: dict[str, Any]):
        self._message_id = message_id
        self._body = body

    @property
    def id(self) -> str:
        return self._message_id

    @property
    def event_type(self) -> str:
        return str(self._body.get("event_type", "UNKNOWN"))

    @property
    def body(self) -> dict[str, Any]:
        return self._body


class ListenNotifyOutboxAdapter(OutboxPort):
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.pool: asyncpg.Pool | None = None
        self.listener_connection: asyncpg.Connection | None = None
        self._initialized = False

    async def _initialize(self) -> None:
        if self._initialized:
            return

        url = make_url(self.db_url).set(drivername="postgresql")
        asyncpg_url = url.render_as_string(hide_password=False)
        self.pool = await asyncpg.create_pool(asyncpg_url)
        self.listener_connection = await asyncpg.connect(asyncpg_url)
        await self.listener_connection.add_listener("edi_outbox_channel", self._on_notify)
        logger.info("polling_started", channel="edi_outbox_channel")
        self._initialized = True

    async def close(self) -> None:
        """Close the adapter and release all resources."""
        if not self._initialized:
            return

        try:
            if self.listener_connection:
                try:
                    await self.listener_connection.remove_listener(
                        "edi_outbox_channel", self._on_notify
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning("listener_removal_error", error=str(e))
                try:
                    await self.listener_connection.close()
                except Exception as e:  # noqa: BLE001
                    logger.warning("listener_close_error", error=str(e))
                self.listener_connection = None

            if self.pool:
                try:
                    await self.pool.close()
                except Exception as e:  # noqa: BLE001
                    logger.warning("pool_close_error", error=str(e))
                self.pool = None

            self._initialized = False
            logger.info("listener_notify_outbox_adapter_closed")
        except Exception:
            logger.exception("adapter_close_error")

    def _on_notify(
        self, connection: asyncpg.Connection, pid: int, channel: str, payload: str
    ) -> None:
        logger.info("postgres_notify_received", channel=channel, event_id=payload)
        self.queue.put_nowait(payload)

    @asynccontextmanager
    async def process_next_event(self) -> AsyncIterator[OutboxEvent | None]:  # noqa: C901
        if not self._initialized:
            await self._initialize()

        # Check connection health and reconnect if necessary
        if self.listener_connection and self.listener_connection.is_closed():
            logger.warning("asyncpg_connection_lost", action="reconnecting")
            await self.close()
            await self._initialize()

        try:
            # Timeout allows gracefully shutting down
            event_id = await asyncio.wait_for(self.queue.get(), timeout=5.0)
        except TimeoutError:
            yield None
            return

        if not self.pool:
            yield None
            return

        # First transaction: claim the event by changing status to PROCESSING
        async with self.pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                "SELECT id, tenant_id, event_type, payload, status, idempotency_key FROM edi.outbox WHERE id = $1 FOR UPDATE SKIP LOCKED",
                event_id,
            )

            if not row:
                logger.warning("outbox_event_not_found", event_id=event_id)
                yield None
                return

            # Accept both PENDING (from NOTIFY) and PROCESSING (from sweeper)
            # This allows the sweeper to recover stuck/crashed claims
            if row["status"] not in ("PENDING", "PROCESSING"):
                logger.info(
                    "outbox_event_already_processed_or_failed",
                    event_id=event_id,
                    status=row["status"],
                )
                yield None
                return

            # Claim the event (idempotent if already PROCESSING from sweeper)
            await connection.execute(
                "UPDATE edi.outbox SET status = 'PROCESSING' WHERE id = $1",
                event_id,
            )

            # Connection and lock released here

            # Let all events pass through to the Anti-Corruption Layer
            # The core ProvisioningWorkerService will filter out what it doesn't need.

            error_message = None
            processing_error: Exception | None = None
            processing_failed = False

            try:
                payload_data = (
                    json.loads(row["payload"])
                    if isinstance(row["payload"], str)
                    else row["payload"]
                )

                # Normalize to the UCP EventMessage schema contract (matching AWS SNS Router)
                # so that ACL Translators handle a consistent interface regardless of the transport mechanism.
                external_envelope = {
                    "idempotencyKey": row.get("idempotency_key", row["id"]),
                    "tenantId": row["tenant_id"],
                    "eventType": row["event_type"],
                    "payload": payload_data,
                }

                # Apply Anti-Corruption Layer Translation if applicable
                translated_body = translate_external_event(row["event_type"], external_envelope)
                body = translated_body if translated_body is not None else payload_data

                event = PostgresOutboxEvent(
                    message_id=row["id"],
                    body=body,
                )

                logger.info(
                    "yielding_outbox_event",
                    event_id=event_id,
                    event_type=row["event_type"],
                    tenant_id=row["tenant_id"],
                )
                yield event

            except Exception as e:
                logger.exception("postgres_outbox_event_processing_failed", event_id=event_id)

                error_message = str(e)
                processing_error = e
                processing_failed = True

        # Second transaction: mark the event as PROCESSED or FAILED
        if not self.pool:
            return

        async with self.pool.acquire() as connection, connection.transaction():
            if processing_failed:
                await connection.execute(
                    "UPDATE edi.outbox SET status = 'FAILED', attempts = attempts + 1, error_reason = $1 WHERE id = $2",
                    error_message,
                    event_id,
                )
                logger.info("outbox_event_marked_failed", event_id=event_id)
            else:
                logger.info("outbox_event_marked_processed", event_id=event_id)
                await connection.execute(
                    "UPDATE edi.outbox SET status = 'PROCESSED', error_reason = NULL WHERE id = $1",
                    event_id,
                )

        # Re-raise the exception after persisting the failure
        if processing_error is not None:
            raise processing_error

    async def publish_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        tenant_id: str,
    ) -> None:
        """Publishes an event to the outbox queue."""
        if not self.pool:
            raise RuntimeError("Adapter is not initialized")

        async with self.pool.acquire() as connection:
            await connection.execute(
                "INSERT INTO edi.outbox (idempotency_key, event_type, payload, tenant_id, status) VALUES ($1, $2, $3, $4, 'PENDING') ON CONFLICT (idempotency_key) DO NOTHING",
                idempotency_key,
                event_type,
                json.dumps(payload),
                tenant_id,
            )
