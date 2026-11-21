"""In-memory Message Publisher Adapter for zero-infrastructure testing."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from seedwork.domain.exceptions import Result
from seedwork.events import EventEnvelope

from pubsub.domain.dtos import PublishResultDTO
from pubsub.ports.message_publisher_port import MessagePublisherPort


class InMemoryPublisherAdapter(MessagePublisherPort):
    """In-memory publisher storing messages in memory for unit and integration testing."""

    def __init__(self) -> None:
        self.published_messages: list[
            tuple[str, bytes, bytes | None, Mapping[str, str] | None]
        ] = []

    async def publish(
        self,
        destination_uri: str,
        message: bytes | EventEnvelope,
        key: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Result[PublishResultDTO, Exception]:
        if isinstance(message, EventEnvelope):
            raw_body = json.dumps(message.to_dict()).encode("utf-8")
            event_key = message.idempotency_key.encode("utf-8") if message.idempotency_key else None
            effective_key = key or event_key
            merged_headers = dict(headers or {})
            merged_headers["event_type"] = message.event_type
            merged_headers["event_id"] = message.id
        else:
            raw_body = message
            effective_key = key
            merged_headers = dict(headers or {})

        self.published_messages.append((destination_uri, raw_body, effective_key, merged_headers))
        result = PublishResultDTO(
            destination_uri=destination_uri,
            message_id=f"mem_{len(self.published_messages) - 1}",
            partition=0,
            offset=len(self.published_messages) - 1,
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

    def clear(self) -> None:
        self.published_messages.clear()
