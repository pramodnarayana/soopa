"""Unit tests for StreamSubscriptionSupervisor verifying isolated worker task lifecycle."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from ip.engine.application.use_cases.ingestion.ingest_stream_batch_use_case import (
    IngestStreamBatchCommand,
    IngestStreamBatchResultDTO,
    IngestStreamBatchUseCase,
)
from ip.engine.application.use_cases.ingestion.stream_subscription_supervisor import (
    StreamSubscriptionSupervisor,
)
from ip.engine.domain.enums import AckVerdict
from ip.engine.domain.exceptions import ConnectionCheckError, Result
from ip.engine.domain.models.stream_definition import StreamDefinition
from ip.engine.ports.outbound.subscribe_transport_port import (
    RawMessageBatchDTO,
    RawMessageDTO,
    SubscribeTransportPort,
)
from seedwork.domain.types import JsonDict


class MockTransport(SubscribeTransportPort):
    def __init__(self, message_to_yield: RawMessageDTO) -> None:
        self.message_to_yield = message_to_yield
        self.started = False
        self.stopped = False
        self.delivered_verdict: AckVerdict | None = None

    async def test_connection(
        self, config: JsonDict, credentials: JsonDict
    ) -> Result[None, ConnectionCheckError]:
        return Result.ok(None)

    async def start_consumer(
        self,
        stream: StreamDefinition,
        message_handler: Callable[[RawMessageBatchDTO], Awaitable[AckVerdict]],
        stop_signal: asyncio.Event,
    ) -> None:
        self.started = True
        batch = RawMessageBatchDTO(stream_name=stream.stream, messages=[self.message_to_yield])
        self.delivered_verdict = await message_handler(batch)
        await stop_signal.wait()
        self.stopped = True


class FakeIngestUseCase(IngestStreamBatchUseCase):
    def __init__(self) -> None:
        self.executed_commands: list[IngestStreamBatchCommand] = []

    async def execute(self, command: IngestStreamBatchCommand) -> IngestStreamBatchResultDTO:
        self.executed_commands.append(command)
        return IngestStreamBatchResultDTO(
            verdict=AckVerdict.ACK,
            records_ingested=len(command.batch.messages),
            duplicates_skipped=0,
            trace_id="trc_test",
        )


@pytest.mark.asyncio
async def test_stream_subscription_supervisor_lifecycle() -> None:
    msg = RawMessageDTO(message_id="msg_1", raw_payload=b'{"val":42}')
    transport = MockTransport(msg)
    ingest_use_case = FakeIngestUseCase()

    supervisor = StreamSubscriptionSupervisor(
        ingest_use_case=lambda: ingest_use_case,
        transports={"conn_stream_1": transport},
    )

    stream = StreamDefinition(stream="telemetry")
    supervisor.start_subscription(
        tenant_id="tenant_a",
        connection_id="conn_stream_1",
        app_id="meter_broker",
        stream=stream,
    )

    # Let the event loop cycle so the background task begins
    await asyncio.sleep(0.05)

    assert "conn_stream_1:telemetry" in supervisor.active_subscription_keys
    assert transport.started is True
    assert transport.delivered_verdict == AckVerdict.ACK
    assert len(ingest_use_case.executed_commands) == 1
    assert ingest_use_case.executed_commands[0].stream_name == "telemetry"

    # Stop subscription
    await supervisor.stop_subscription("conn_stream_1", "telemetry")
    await asyncio.sleep(0.05)

    assert transport.stopped is True
    assert "conn_stream_1:telemetry" not in supervisor.active_subscription_keys
