import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg

from worker.adapters.acl.registry import translate_external_event
from worker.ports.outbox import OutboxEvent, OutboxPort

logger = logging.getLogger(__name__)


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

        asyncpg_url = self.db_url.replace("postgresql+asyncpg://", "postgresql://")
        self.pool = await asyncpg.create_pool(asyncpg_url)
        self.listener_connection = await asyncpg.connect(asyncpg_url)
        await self.listener_connection.add_listener("edi_outbox_channel", self._on_notify)
        logger.info("Started polling Postgres LISTEN for PROVISION events")
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
                except Exception as e:
                    logger.warning(f"Error removing listener: {e}")
                try:
                    await self.listener_connection.close()
                except Exception as e:
                    logger.warning(f"Error closing listener connection: {e}")
                self.listener_connection = None

            if self.pool:
                try:
                    await self.pool.close()
                except Exception as e:
                    logger.warning(f"Error closing pool: {e}")
                self.pool = None

            self._initialized = False
            logger.info("Closed ListenNotifyOutboxAdapter resources")
        except Exception as e:
            logger.exception(f"Error during adapter close: {e}")

    def _on_notify(
        self, connection: asyncpg.Connection, pid: int, channel: str, payload: str
    ) -> None:
        logger.debug(f"Received NOTIFY on {channel}: {payload}")
        self.queue.put_nowait(payload)

    @asynccontextmanager
    async def process_next_event(self) -> AsyncIterator[OutboxEvent | None]:
        if not self._initialized:
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
                logger.debug(f"Event {event_id} not found.")
                yield None
                return

            # Accept both PENDING (from NOTIFY) and PROCESSING (from sweeper)
            # This allows the sweeper to recover stuck/crashed claims
            if row["status"] not in ("PENDING", "PROCESSING"):
                logger.debug(f"Event {event_id} already processed (status: {row['status']}).")
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
                    f"Picked up outbox event {event_id} (type: {row['event_type']}, tenant_id: {row['tenant_id']})"
                )
                yield event

            except Exception as e:
                logger.exception(f"Error processing Postgres outbox event {event_id}: {e}")
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
                logger.info(f"Marked outbox event {event_id} as FAILED")
            else:
                logger.info(f"Successfully processed outbox event {event_id}, marking as PROCESSED")
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
