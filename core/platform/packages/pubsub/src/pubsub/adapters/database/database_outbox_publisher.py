"""Durable PostgreSQL OutboxPublisherPort and MessagePublisherPort for `db://` / `outbox://` URIs."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence

import structlog
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from seedwork.domain.exceptions import Result
from seedwork.events import EventEnvelope
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id

from pubsub.domain.dtos import PublishResultDTO
from pubsub.domain.enums import (
    is_database_topic_uri,
    normalize_database_queue_name,
    normalize_database_topic_name,
)
from pubsub.ports.database_queue_port import DatabaseQueuePort
from pubsub.ports.message_publisher_port import MessagePublisherPort

logger = structlog.get_logger(__name__)


class DatabaseOutboxPublisher(OutboxPublisherPort):
    """Durable OutboxPublisherPort publishing to `db://<queue>` or fanning out via `db://topic/<topic>`."""

    def __init__(
        self,
        database_queue: DatabaseQueuePort,
        destination_uri: str = "db://outbox",
        *,
        owned_db_close: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._database_queue = database_queue
        self._owned_db_close = owned_db_close
        self.destination_uri = destination_uri
        self.is_topic = is_database_topic_uri(destination_uri)
        self.queue_name = (
            normalize_database_topic_name(destination_uri)
            if self.is_topic
            else normalize_database_queue_name(destination_uri)
        )

    async def aclose(self) -> None:
        if self._owned_db_close is not None:
            await self._owned_db_close()
            self._owned_db_close = None

    async def publish(self, event: EventEnvelope) -> None:
        if self.is_topic:
            await self._database_queue.publish_to_topic(self.queue_name, event)
        else:
            await self._database_queue.enqueue(self.queue_name, event)
        logger.info(
            "database_outbox_event_published",
            destination=self.destination_uri,
            target=self.queue_name,
            is_topic=self.is_topic,
            event_id=event.id,
            event_type=event.event_type,
        )

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        if self.is_topic:
            return await self._database_queue.publish_batch_to_topic(self.queue_name, events)
        return await self._database_queue.enqueue_batch(self.queue_name, events)


class DatabasePublisherAdapter(MessagePublisherPort):
    """Durable MessagePublisherPort publishing to `db://<queue>` or `db://topic/<topic>`."""

    def __init__(
        self,
        database_queue: DatabaseQueuePort,
        *,
        owned_db_close: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._database_queue = database_queue
        self._owned_db_close = owned_db_close

    async def aclose(self) -> None:
        if self._owned_db_close is not None:
            await self._owned_db_close()
            self._owned_db_close = None

    async def publish(
        self,
        destination_uri: str,
        message: bytes | EventEnvelope,
        key: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Result[PublishResultDTO, Exception]:
        is_topic = is_database_topic_uri(destination_uri)
        target_name = (
            normalize_database_topic_name(destination_uri)
            if is_topic
            else normalize_database_queue_name(destination_uri)
        )
        if isinstance(message, EventEnvelope):
            envelope = message
        else:
            try:
                loaded = json.loads(message.decode("utf-8"))
                payload_dict = loaded if isinstance(loaded, dict) else {"data": loaded}
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                logger.error(
                    "database_publisher_malformed_json",
                    destination_uri=destination_uri,
                    error=str(exc),
                )
                return Result.fail(ValueError(f"Invalid JSON payload for {destination_uri}: {exc}"))
            envelope = EventEnvelope(
                id=str(payload_dict.get("job_id") or generate_id(SystemIdPrefix.GENERIC)),
                source="database_publisher",
                event_type=str(
                    payload_dict.get("event_type")
                    or payload_dict.get("job_name")
                    or "direct.message"
                ),
                tenant_id=str(payload_dict.get("tenant_id", "platform")),
                idempotency_key=str(
                    payload_dict.get("idempotency_key") or generate_id(SystemIdPrefix.IDEMPOTENCY)
                ),
                payload=payload_dict,
            )

        try:
            if is_topic:
                await self._database_queue.publish_to_topic(target_name, envelope)
            else:
                await self._database_queue.enqueue(target_name, envelope)
        except Exception as exc:
            logger.exception(
                "database_publisher_enqueue_failed",
                destination_uri=destination_uri,
                target=target_name,
                is_topic=is_topic,
                error=str(exc),
            )
            return Result.fail(exc)

        return Result.ok(
            PublishResultDTO(
                destination_uri=destination_uri,
                message_id=envelope.id,
            )
        )

    async def publish_batch(
        self,
        destination_uri: str,
        messages: Sequence[bytes | EventEnvelope],
        keys: Sequence[bytes | None] | None = None,
        headers: Sequence[Mapping[str, str] | None] | None = None,
    ) -> Result[tuple[PublishResultDTO, ...], Exception]:
        results: list[PublishResultDTO] = []
        for idx, msg in enumerate(messages):
            k = keys[idx] if keys and idx < len(keys) else None
            h = headers[idx] if headers and idx < len(headers) else None
            res = await self.publish(destination_uri, msg, key=k, headers=h)
            if res.is_err:
                err = res.error if res.error is not None else RuntimeError("Unknown publish error")
                return Result.fail(err)
            results.append(res.unwrap())
        return Result.ok(tuple(results))
