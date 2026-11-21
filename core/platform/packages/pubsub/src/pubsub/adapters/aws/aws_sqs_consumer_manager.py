"""AWS SQS Consumer Manager implementing ConsumerManagerPort."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
from collections.abc import Awaitable, Callable
from typing import cast

import structlog
from seedwork.domain.types import JsonDict

from pubsub.adapters.aws.error_handlers import DefaultConsumerErrorHandler
from pubsub.domain.dtos import AckableMessage
from pubsub.domain.enums import ConsumerVerdict
from pubsub.enums import ConsumerAction, ConsumerDecision, ConsumerOutcome
from pubsub.exceptions import ConsumerTerminalError, ConsumerTransientError
from pubsub.ports.consumer_error_handler_port import ConsumerErrorHandlerPort
from pubsub.ports.consumer_manager_port import ConsumerManagerPort, MessageHandler
from pubsub.ports.message_consumer_port import MessageConsumerPort

logger = structlog.get_logger(__name__)


async def _execute_ack(msg: AckableMessage) -> None:
    await msg.ack()


async def _execute_nack(msg: AckableMessage) -> None:
    await msg.nack()


CONSUMER_ACTION_STRATEGIES: dict[ConsumerAction, Callable[[AckableMessage], Awaitable[None]]] = {
    ConsumerAction.ACK: _execute_ack,
    ConsumerAction.NACK: _execute_nack,
    ConsumerAction.DLQ: _execute_nack,
}


class AwsSqsConsumerManager(ConsumerManagerPort):
    """
    Centralized Message Pump for polling AWS SQS and dispatching to a
    pure domain callback handler. Implements ConsumerManagerPort.
    """

    def __init__(
        self,
        consumer: MessageConsumerPort,
        handler: MessageHandler,
        queue_name: str = "",
        poll_sleep_seconds: float = 0.1,
        error_sleep_seconds: float = 5.0,
        error_handler: ConsumerErrorHandlerPort | None = None,
        on_fatal_error: Callable[[BaseException], None] | None = None,
    ) -> None:
        self.consumer = consumer
        self.handler = handler
        self.queue_name = queue_name
        self.poll_sleep_seconds = poll_sleep_seconds
        self.error_sleep_seconds = error_sleep_seconds
        self.on_fatal_error = on_fatal_error
        self.error_handler = error_handler or DefaultConsumerErrorHandler(error_sleep_seconds)

        self._pass_payload_only = self._detect_payload_mode(handler)
        self.is_running = False
        self._task: asyncio.Task[None] | None = None

    @staticmethod
    def _detect_payload_mode(handler: MessageHandler) -> bool:
        """Determines if the handler expects JsonDict payload rather than AckableMessage."""
        try:
            sig = inspect.signature(handler)
            params = [
                p
                for p in sig.parameters.values()
                if p.kind
                in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                )
            ]
            if params:
                first = params[0]
                if first.annotation in (AckableMessage, "AckableMessage"):
                    return False
                if first.name in ("ackable_msg", "ackable_message", "ackable"):
                    return False
                if first.name in ("body", "payload", "message", "msg", "data", "event"):
                    return True
                ann = first.annotation
                if ann is inspect.Parameter.empty:
                    return True
                ann_str = str(ann).lower()
                if any(t in ann_str for t in ("dict", "mapping", "envelope", "json")):
                    return True
        except (ValueError, TypeError):
            pass
        return True

    def background_tasks(self) -> list[asyncio.Task[object]]:
        if self._task is not None:
            return [self._task]
        return []

    @property
    def task(self) -> asyncio.Task[None] | None:
        return self._task

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            exc = task.exception()
            if exc:
                logger.error(
                    "sqs_consumer_manager_background_task_crashed",
                    queue=self.queue_name,
                    exc_info=exc,
                )
                if self.on_fatal_error:
                    self.on_fatal_error(exc)
                else:
                    loop = asyncio.get_event_loop()
                    loop.call_soon_threadsafe(loop.stop)

    def start(self) -> None:
        if not self.is_running:
            self.is_running = True
            self._task = asyncio.create_task(self._run_loop())
            self._task.add_done_callback(self._on_task_done)
            logger.info("sqs_consumer_manager_started", queue=self.queue_name)

    async def stop(self) -> None:
        self.is_running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("sqs_consumer_manager_stopped", queue=self.queue_name)

    async def health_check(self) -> bool:
        return self.is_running and (self._task is None or not self._task.done())

    async def _run_loop(self) -> None:
        while self.is_running:
            try:
                async with self.consumer:
                    await self._poll_continuous()
            except asyncio.CancelledError:
                self.is_running = False
                raise
            except ConsumerTerminalError:
                logger.error("sqs_consumer_manager_terminal_error", queue=self.queue_name)
                raise
            except ConsumerTransientError as e:
                logger.warning(
                    "sqs_consumer_manager_transient_error", queue=self.queue_name, reason=str(e)
                )
                await asyncio.sleep(self.error_sleep_seconds)
            except Exception:
                logger.exception(
                    "sqs_consumer_manager_unhandled_fatal_error", queue=self.queue_name
                )
                raise

    async def _dispatch_to_handler(
        self, ackable_msg: AckableMessage
    ) -> ConsumerOutcome | ConsumerVerdict | None:
        if self._pass_payload_only:
            handler_dict = cast(
                Callable[[JsonDict], Awaitable[ConsumerOutcome | None]], self.handler
            )
            payload_dict: JsonDict
            if isinstance(ackable_msg.payload, dict):
                payload_dict = ackable_msg.payload
            elif isinstance(ackable_msg.payload, (str, bytes)):
                try:
                    loaded = json.loads(ackable_msg.payload)
                    payload_dict = loaded if isinstance(loaded, dict) else {"data": loaded}
                except (json.JSONDecodeError, UnicodeDecodeError):
                    logger.error(
                        "sqs_consumer_manager_malformed_payload_json",
                        queue=self.queue_name,
                    )
                    payload_dict = {}
            else:
                payload_dict = {}
            return await handler_dict(payload_dict)

        handler_msg = cast(
            Callable[[AckableMessage], Awaitable[ConsumerVerdict | None]], self.handler
        )
        return await handler_msg(ackable_msg)

    @staticmethod
    async def _apply_outcome(
        ackable_msg: AckableMessage,
        outcome: ConsumerOutcome | ConsumerVerdict | None,
    ) -> None:
        if isinstance(outcome, ConsumerDecision):
            if outcome.action in (ConsumerAction.NACK, ConsumerAction.DLQ):
                await ackable_msg.nack(
                    visibility_timeout_seconds=outcome.visibility_timeout_seconds
                )
            else:
                await ackable_msg.ack()
        elif isinstance(outcome, ConsumerVerdict):
            if outcome == ConsumerVerdict.ACK:
                await ackable_msg.ack()
            else:
                await ackable_msg.nack()
        else:
            resolved_action = outcome or ConsumerAction.ACK
            strategy_fn = CONSUMER_ACTION_STRATEGIES.get(resolved_action, _execute_ack)
            await strategy_fn(ackable_msg)

    async def _poll_continuous(self) -> None:
        while self.is_running:
            ackable_msg: AckableMessage | None = None
            try:
                async with self.consumer.poll_raw_message() as ackable_msg:
                    if not ackable_msg:
                        await asyncio.sleep(self.poll_sleep_seconds)
                        continue

                    keys: list[str] = []
                    if isinstance(ackable_msg.payload, dict):
                        keys = list(ackable_msg.payload.keys())

                    logger.info(
                        "sqs_consumer_manager_received_message",
                        queue=self.queue_name,
                        payload_keys=keys,
                    )

                    outcome = await self._dispatch_to_handler(ackable_msg)
                    await self._apply_outcome(ackable_msg, outcome)

            except asyncio.CancelledError:
                break
            except ConsumerTerminalError as e:
                if ackable_msg is not None:
                    logger.error(
                        "sqs_consumer_manager_terminal_payload_error",
                        queue=self.queue_name,
                        error=str(e),
                    )
                    await ackable_msg.ack()
                else:
                    raise
            except Exception as e:  # noqa: BLE001 - Injected ErrorHandlerStrategy handles all unexpected consumer errors
                await self.error_handler.handle_error(e, ackable_msg, self.queue_name)
