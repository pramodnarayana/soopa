import pytest
from edi.application.use_cases.pipeline.compute_outbound_transform_use_case import (
    ComputeOutboundTransformCommand,
)
from edi.application.use_cases.pipeline.compute_transform_use_case import ComputeTransformCommand

from compute_worker.compute_dispatcher import EdiComputeDispatcher


class FakeComputeTransformUseCase:
    """Typed fake for ComputeTransformUseCase. Records the command it was called with."""

    called_command: ComputeTransformCommand | None = None

    async def execute(self, command: ComputeTransformCommand) -> None:
        self.called_command = command


class FakeComputeOutboundTransformUseCase:
    """Typed fake for ComputeOutboundTransformUseCase. Records the command it was called with."""

    called_command: ComputeOutboundTransformCommand | None = None

    async def execute(self, command: ComputeOutboundTransformCommand) -> None:
        self.called_command = command


@pytest.mark.asyncio
async def test_dispatcher_process_inbound_message_success() -> None:
    """Dispatcher correctly parses an inbound Debezium body and threads all fields
    — including idempotency_key — into the ComputeTransformCommand."""
    fake_use_case = FakeComputeTransformUseCase()

    async def fake_factory(tenant_id: str) -> FakeComputeTransformUseCase:
        assert tenant_id == "tenant-1"
        return fake_use_case

    async def fake_outbound_factory(tenant_id: str) -> FakeComputeOutboundTransformUseCase:
        raise AssertionError("outbound factory must not be called for an INBOUND message")

    dispatcher = EdiComputeDispatcher(
        use_case_factory=fake_factory, outbound_use_case_factory=fake_outbound_factory
    )

    message_body = {
        "idempotency_key": "sys_idemp_test-inbound-success",
        "payload": {"trace_id": "trace-123", "tenant_id": "tenant-1"},
    }

    await dispatcher.dispatch_raw(message_body)

    assert fake_use_case.called_command is not None
    assert fake_use_case.called_command.trace_id == "trace-123"
    assert fake_use_case.called_command.tenant_id == "tenant-1"
    # Critical: verify the idempotency_key is correctly propagated from body into the command.
    assert fake_use_case.called_command.idempotency_key == "sys_idemp_test-inbound-success"


@pytest.mark.asyncio
async def test_dispatcher_drops_message_with_missing_idempotency_key() -> None:
    """Dispatcher must drop (not raise) messages that have no top-level idempotency_key.
    This covers the new guard that prevents mistaking trace_id for the idempotency fence."""
    fake_use_case = FakeComputeTransformUseCase()

    async def fake_factory(tenant_id: str) -> FakeComputeTransformUseCase:
        return fake_use_case

    async def fake_outbound_factory(tenant_id: str) -> FakeComputeOutboundTransformUseCase:
        raise AssertionError("outbound factory must not be called")

    dispatcher = EdiComputeDispatcher(
        use_case_factory=fake_factory, outbound_use_case_factory=fake_outbound_factory
    )

    # Body has no idempotency_key — message must be silently dropped, not raise.
    message_body = {"payload": {"trace_id": "trace-123", "tenant_id": "tenant-1"}}

    await dispatcher.dispatch_raw(message_body)

    assert fake_use_case.called_command is None


@pytest.mark.asyncio
async def test_dispatcher_drops_message_with_missing_trace_id() -> None:
    """Dispatcher rejects messages missing trace_id without invoking the use case."""
    fake_use_case = FakeComputeTransformUseCase()

    async def fake_factory(tenant_id: str) -> FakeComputeTransformUseCase:
        return fake_use_case

    async def fake_outbound_factory(tenant_id: str) -> FakeComputeOutboundTransformUseCase:
        raise AssertionError("outbound factory must not be called")

    dispatcher = EdiComputeDispatcher(
        use_case_factory=fake_factory, outbound_use_case_factory=fake_outbound_factory
    )

    message_body = {
        "idempotency_key": "sys_idemp_test-missing-trace-id",
        "payload": {"tenant_id": "tenant-1"},
    }

    await dispatcher.dispatch_raw(message_body)

    assert fake_use_case.called_command is None


@pytest.mark.asyncio
async def test_dispatcher_process_outbound_message_success() -> None:
    """Dispatcher correctly parses an outbound Debezium body and threads all fields
    — including idempotency_key — into the ComputeOutboundTransformCommand."""
    fake_outbound_use_case = FakeComputeOutboundTransformUseCase()

    async def fake_factory(tenant_id: str) -> FakeComputeTransformUseCase:
        raise AssertionError("inbound factory must not be called for an OUTBOUND message")

    async def fake_outbound_factory(tenant_id: str) -> FakeComputeOutboundTransformUseCase:
        assert tenant_id == "tenant-1"
        return fake_outbound_use_case

    dispatcher = EdiComputeDispatcher(
        use_case_factory=fake_factory, outbound_use_case_factory=fake_outbound_factory
    )

    message_body = {
        "idempotency_key": "sys_idemp_test-outbound-success",
        "payload": {
            "trace_id": "trace-123",
            "tenant_id": "tenant-1",
            "direction": "OUTBOUND",
            "transaction_type": "850",
            "route_config": {"as2_partner_id": "p-1", "connection_type": "AS2"},
        },
    }

    await dispatcher.dispatch_raw(message_body)

    assert fake_outbound_use_case.called_command is not None
    assert fake_outbound_use_case.called_command.trace_id == "trace-123"
    assert fake_outbound_use_case.called_command.tenant_id == "tenant-1"
    # Critical: verify the idempotency_key is correctly propagated from body into the command.
    assert (
        fake_outbound_use_case.called_command.idempotency_key == "sys_idemp_test-outbound-success"
    )


@pytest.mark.asyncio
async def test_dispatcher_drops_outbound_message_missing_transaction_type() -> None:
    """Dispatcher rejects outbound messages missing transaction_type without invoking use case."""
    fake_outbound_use_case = FakeComputeOutboundTransformUseCase()

    async def fake_factory(tenant_id: str) -> FakeComputeTransformUseCase:
        raise AssertionError("inbound factory must not be called")

    async def fake_outbound_factory(tenant_id: str) -> FakeComputeOutboundTransformUseCase:
        return fake_outbound_use_case

    dispatcher = EdiComputeDispatcher(
        use_case_factory=fake_factory, outbound_use_case_factory=fake_outbound_factory
    )

    message_body = {
        "idempotency_key": "sys_idemp_test-missing-txn-type",
        "payload": {
            "trace_id": "trace-123",
            "tenant_id": "tenant-1",
            "direction": "OUTBOUND",
        },
    }

    await dispatcher.dispatch_raw(message_body)

    assert fake_outbound_use_case.called_command is None


@pytest.mark.asyncio
async def test_dispatcher_drops_message_with_invalid_direction() -> None:
    """Dispatcher rejects messages with unrecognised direction strings."""
    fake_use_case = FakeComputeTransformUseCase()

    async def fake_factory(tenant_id: str) -> FakeComputeTransformUseCase:
        return fake_use_case

    async def fake_outbound_factory(tenant_id: str) -> FakeComputeOutboundTransformUseCase:
        raise AssertionError("outbound factory must not be called")

    dispatcher = EdiComputeDispatcher(
        use_case_factory=fake_factory, outbound_use_case_factory=fake_outbound_factory
    )

    message_body = {
        "idempotency_key": "sys_idemp_test-invalid-direction",
        "payload": {
            "trace_id": "trace-123",
            "tenant_id": "tenant-1",
            "direction": "invalid_dir",
        },
    }

    await dispatcher.dispatch_raw(message_body)

    assert fake_use_case.called_command is None
