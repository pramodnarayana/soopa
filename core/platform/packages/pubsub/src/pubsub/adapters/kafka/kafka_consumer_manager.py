"""Enterprise Apache Kafka Consumer Manager backed by confluent-kafka (librdkafka)."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import cast

import structlog
from confluent_kafka import Consumer, KafkaError, Message

from pubsub.domain.dtos import AckableMessage
from pubsub.domain.enums import ConsumerVerdict
from pubsub.ports.consumer_manager_port import ConsumerManagerPort, MessageHandler

logger = structlog.get_logger(__name__)


class KafkaConsumerManager(ConsumerManagerPort):
    """Background message pump consuming from Apache Kafka with strict manual commit."""

    def __init__(
        self,
        topic: str,
        group_id: str,
        handler: MessageHandler,
        bootstrap_servers: str = "localhost:9092",
        auto_offset_reset: str = "earliest",
        consumer: Consumer | None = None,
        poll_timeout_seconds: float = 1.0,
    ) -> None:
        self._topic = topic.removeprefix("kafka://")
        self._group_id = group_id
        self._handler = handler
        self._bootstrap_servers = bootstrap_servers
        self._auto_offset_reset = auto_offset_reset
        self._consumer = consumer
        self._poll_timeout_seconds = poll_timeout_seconds

        self._running = False
        self._task: asyncio.Task[None] | None = None

    def _get_consumer(self) -> Consumer:
        if self._consumer is None:
            conf: dict[str, str | bool | int] = {
                "bootstrap.servers": self._bootstrap_servers,
                "group.id": self._group_id,
                "auto.offset.reset": self._auto_offset_reset,
                "enable.auto.commit": False,
                "session.timeout.ms": 30000,
                "max.poll.interval.ms": 300000,
            }
            self._consumer = Consumer(conf)
            self._consumer.subscribe([self._topic])
        return self._consumer

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            "kafka_consumer_manager_started",
            topic=self._topic,
            group_id=self._group_id,
        )

    @property
    def task(self) -> asyncio.Task[None] | None:
        return self._task

    def background_tasks(self) -> list[asyncio.Task[object]]:
        if self._task is not None:
            return [self._task]
        return []

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

        if self._consumer is not None:
            await asyncio.to_thread(self._consumer.close)
            self._consumer = None

        logger.info(
            "kafka_consumer_manager_stopped",
            topic=self._topic,
            group_id=self._group_id,
        )

    async def health_check(self) -> bool:
        return self._running and (self._task is None or not self._task.done())

    async def _poll_loop(self) -> None:
        consumer = self._get_consumer()
        while self._running:
            try:
                msg: Message | None = await asyncio.to_thread(
                    consumer.poll, self._poll_timeout_seconds
                )
                if msg is None:
                    continue

                msg_err = msg.error()
                if msg_err is not None:
                    if msg_err.code() == KafkaError._PARTITION_EOF:
                        continue
                    logger.error(
                        "kafka_consumer_poll_error",
                        topic=self._topic,
                        error=msg_err.str(),
                    )
                    continue

                await self._dispatch_message(consumer, msg)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("kafka_consumer_loop_error", topic=self._topic, error=str(exc))
                await asyncio.sleep(0.5)

    async def _dispatch_message(self, consumer: Consumer, msg: Message) -> None:
        raw_payload = msg.value() or b""
        raw_headers = msg.headers()
        parsed_headers: dict[str, str] = {}
        if raw_headers is not None:
            for item in raw_headers:
                if isinstance(item, tuple) and len(item) == 2:
                    k, v = item
                    parsed_headers[str(k)] = (
                        v.decode("utf-8", errors="replace")
                        if isinstance(v, bytes)
                        else str(v or "")
                    )

        async def _ack() -> None:
            await asyncio.to_thread(consumer.commit, message=msg, asynchronous=False)

        async def _nack(
            *, requeue: bool = True, visibility_timeout_seconds: int | None = None
        ) -> None:
            # For Kafka, NACK rolls back position to uncommitted offset or skips
            logger.warning(
                "kafka_message_nacked",
                topic=msg.topic(),
                partition=msg.partition(),
                offset=msg.offset(),
            )

        ackable = AckableMessage(
            payload=raw_payload,
            headers=parsed_headers,
            key=msg.key(),
            ack=_ack,
            nack=_nack,
            destination_uri=f"kafka://{msg.topic()}",
            message_id=f"{msg.topic()}:{msg.partition()}:{msg.offset()}",
            partition=msg.partition(),
            offset=msg.offset(),
        )

        try:
            handler_fn = cast(
                Callable[[AckableMessage], Awaitable[ConsumerVerdict | None]], self._handler
            )
            verdict = await handler_fn(ackable)
            if verdict == ConsumerVerdict.ACK or verdict is None:
                await _ack()
            elif verdict == ConsumerVerdict.NACK:
                await _nack(requeue=True)
            elif verdict == ConsumerVerdict.REJECT:
                await _ack()  # Dropped/committed without processing
        except Exception:
            logger.exception(
                "kafka_handler_unhandled_failure", topic=msg.topic(), offset=msg.offset()
            )
            await _nack(requeue=True)
            raise
