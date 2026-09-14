import pytest
from edi.adapters.outbound.transformer.domain.models import ParsedEdiPayload

from compute_worker.compute_dispatcher import EdiComputeDispatcher


class FakeProcessInboundEdiUseCase:
    def __init__(self):
        self.called_trace_id = None
        self.called_s3_uri = None
        self.called_standard = None
        self.called_transaction_type = None

    async def execute(self, command) -> ParsedEdiPayload:
        self.called_trace_id = command.trace_id
        self.called_standard = command.standard
        self.called_transaction_type = command.transaction_type

        if not command.trace_id or command.trace_id == "unknown":
            raise ValueError("Invalid trace ID")

        return ParsedEdiPayload(
            sender_id="TEST", receiver_id="TEST", interchange_control_number="1", transactions=[]
        )


@pytest.mark.asyncio
async def test_dispatcher_process_message_success():
    """Tests that the dispatcher parses payload and routes it to the use case."""
    fake_use_case = FakeProcessInboundEdiUseCase()

    async def fake_factory(tenant_id: str):
        assert tenant_id == "1"
        return fake_use_case

    async def fake_outbound_factory(tenant_id: str):
        pass

    dispatcher = EdiComputeDispatcher(
        use_case_factory=fake_factory, outbound_use_case_factory=fake_outbound_factory
    )

    message_body = {
        "payload": {"trace_id": "trace-123", "tenant_id": "1", "s3_uri": "s3://edi/123.x12"}
    }

    await dispatcher.dispatch_raw(message_body)

    assert fake_use_case.called_trace_id == "trace-123"


@pytest.mark.asyncio
async def test_dispatcher_process_message_error_handling():
    """Tests that the dispatcher rejects invalid message bodies without invoking the use case."""
    fake_use_case = FakeProcessInboundEdiUseCase()

    async def fake_factory(tenant_id: str):
        return fake_use_case

    async def fake_outbound_factory(tenant_id: str):
        pass

    dispatcher = EdiComputeDispatcher(
        use_case_factory=fake_factory, outbound_use_case_factory=fake_outbound_factory
    )

    # missing trace_id should be rejected before the use case runs
    message_body = {"payload": {"s3_uri": "s3://edi/123.x12", "tenant_id": "1"}}

    # Should not raise exception (InvalidMessageError is swallowed so message gets deleted)
    await dispatcher.dispatch_raw(message_body)

    # Use case should not have been called with invalid data
    assert fake_use_case.called_trace_id is None


@pytest.mark.asyncio
async def test_dispatcher_process_outbound_message_success():
    """Tests that the dispatcher parses an outbound payload and routes it to the outbound use case."""
    fake_outbound_use_case = FakeProcessInboundEdiUseCase()

    async def fake_factory(tenant_id: str):
        pass

    async def fake_outbound_factory(tenant_id: str):
        assert tenant_id == "1"
        return fake_outbound_use_case

    dispatcher = EdiComputeDispatcher(
        use_case_factory=fake_factory, outbound_use_case_factory=fake_outbound_factory
    )

    message_body = {
        "payload": {
            "trace_id": "trace-123",
            "tenant_id": "1",
            "direction": "OUTBOUND",
            "transaction_type": "850",
            "route_config": {"as2_partner_id": "p-1"},
        }
    }

    await dispatcher.dispatch_raw(message_body)

    assert fake_outbound_use_case.called_trace_id == "trace-123"


@pytest.mark.asyncio
async def test_dispatcher_process_outbound_message_missing_type():
    """Tests that the dispatcher rejects outbound messages missing transaction_type."""
    fake_outbound_use_case = FakeProcessInboundEdiUseCase()

    async def fake_factory(tenant_id: str):
        pass

    async def fake_outbound_factory(tenant_id: str):
        return fake_outbound_use_case

    dispatcher = EdiComputeDispatcher(
        use_case_factory=fake_factory, outbound_use_case_factory=fake_outbound_factory
    )

    # Missing transaction_type for outbound should fail
    message_body = {
        "payload": {
            "trace_id": "trace-123",
            "tenant_id": "1",
            "direction": "OUTBOUND",
        }
    }

    # Should not raise exception (swallowed)
    await dispatcher.dispatch_raw(message_body)

    # Use case should not be called
    assert fake_outbound_use_case.called_trace_id is None


@pytest.mark.asyncio
async def test_dispatcher_process_invalid_direction():
    """Tests that the dispatcher rejects invalid direction strings."""
    fake_use_case = FakeProcessInboundEdiUseCase()

    async def fake_factory(tenant_id: str):
        return fake_use_case

    async def fake_outbound_factory(tenant_id: str):
        return fake_use_case

    dispatcher = EdiComputeDispatcher(
        use_case_factory=fake_factory, outbound_use_case_factory=fake_outbound_factory
    )

    message_body = {
        "payload": {
            "trace_id": "trace-123",
            "tenant_id": "1",
            "direction": "invalid_dir",
        }
    }

    await dispatcher.dispatch_raw(message_body)
    assert fake_use_case.called_trace_id is None
