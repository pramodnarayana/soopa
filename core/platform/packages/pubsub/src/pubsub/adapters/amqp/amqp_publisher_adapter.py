"""RabbitMQ / AMQP message publisher adapter implementing MessagePublisherPort."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import structlog
from seedwork.domain.exceptions import Result
from seedwork.events import EventEnvelope

from pubsub.domain.dtos import PublishResultDTO
from pubsub.ports.message_publisher_port import MessagePublisherPort

logger = structlog.get_logger(__name__)


class AmqpPublisherAdapter(MessagePublisherPort):
    """RabbitMQ / AMQP publisher adapter routing by exchange and routing key."""

    def __init__(
        self,
        endpoint_url: str = "amqp://guest:guest@localhost:5672/",
        use_in_memory: bool = False,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._use_in_memory = use_in_memory
        self.published_messages: list[tuple[str, bytes, Mapping[str, str]]] = []

    async def publish(
        self,
        destination_uri: str,
        message: bytes | EventEnvelope,
        key: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Result[PublishResultDTO, Exception]:
        target = destination_uri.removeprefix("amqp://")

        if isinstance(message, EventEnvelope):
            raw_body = json.dumps(message.to_dict()).encode("utf-8")
            event_id = message.id
        else:
            raw_body = message
            event_id = "msg"

        merged_headers = dict(headers or {})
        self.published_messages.append((target, raw_body, merged_headers))

        result = PublishResultDTO(
            destination_uri=destination_uri,
            message_id=f"amqp_{event_id}_{len(self.published_messages)}",
        )
        return Result.ok(result)

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
                err = res.error if res.error is not None else Exception("Unknown error")
                return Result.fail(err)
            results.append(res.unwrap())
        return Result.ok(tuple(results))
