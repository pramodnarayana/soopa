"""In-memory Consumer Manager for zero-infrastructure testing."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import cast

import structlog

from pubsub.domain.dtos import AckableMessage
from pubsub.domain.enums import ConsumerVerdict
from pubsub.ports.consumer_manager_port import ConsumerManagerPort, MessageHandler

logger = structlog.get_logger(__name__)


class InMemoryConsumerManager(ConsumerManagerPort):
    """In-memory message pump delivering test messages directly to handlers."""

    def __init__(
        self,
        source_uri: str,
        handler: MessageHandler,
    ) -> None:
        self.source_uri = source_uri
        self.handler = handler
        self.acked_message_ids: list[str] = []
        self.nacked_message_ids: list[str] = []
        self.is_running: bool = False

    def start(self) -> None:
        self.is_running = True

    async def stop(self) -> None:
        self.is_running = False

    async def health_check(self) -> bool:
        return self.is_running

    @property
    def task(self) -> asyncio.Task[None] | None:
        return None

    def background_tasks(self) -> list[asyncio.Task[object]]:
        return []

    async def deliver_message(
        self,
        payload: bytes,
        headers: dict[str, str] | None = None,
        key: bytes | None = None,
        message_id: str = "msg_001",
    ) -> ConsumerVerdict | None:
        """Helper to deliver a synthetic message in tests and wait for handler execution."""

        async def _ack() -> None:
            self.acked_message_ids.append(message_id)

        async def _nack(
            *, requeue: bool = True, visibility_timeout_seconds: int | None = None
        ) -> None:
            self.nacked_message_ids.append(message_id)

        ackable = AckableMessage(
            payload=payload,
            headers=headers or {},
            key=key,
            ack=_ack,
            nack=_nack,
            destination_uri=self.source_uri,
            message_id=message_id,
        )

        handler_fn = cast(
            Callable[[AckableMessage], Awaitable[ConsumerVerdict | None]], self.handler
        )
        verdict = await handler_fn(ackable)
        if verdict == ConsumerVerdict.ACK or verdict is None:
            await _ack()
            return ConsumerVerdict.ACK
        if verdict == ConsumerVerdict.NACK:
            await _nack()
            return ConsumerVerdict.NACK
        if verdict == ConsumerVerdict.REJECT:
            await _nack(requeue=False)
            return ConsumerVerdict.REJECT
        return ConsumerVerdict.ACK
