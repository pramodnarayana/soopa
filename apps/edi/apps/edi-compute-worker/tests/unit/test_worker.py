import pytest
from edi.adapters.outbound.transformer.domain.models import ParsedEdiPayload

from compute_worker.compute_dispatcher import EdiComputeDispatcher


class FakeProcessInboundEdiUseCase:
    def __init__(self):
        self.called_trace_id = None
        self.called_s3_uri = None
        self.called_standard = None
        self.called_transaction_type = None

    async def execute(
        self, trace_id: str, standard: str = "X12", transaction_type: str = "UNKNOWN"
    ) -> ParsedEdiPayload:
        self.called_trace_id = trace_id
        self.called_standard = standard
        self.called_transaction_type = transaction_type

        if not trace_id or trace_id == "unknown":
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

    dispatcher = EdiComputeDispatcher(use_case_factory=fake_factory)

    message_body = {"trace_id": "trace-123", "tenant_id": "1", "s3_uri": "s3://edi/123.x12"}

    await dispatcher.dispatch_raw(message_body)

    assert fake_use_case.called_trace_id == "trace-123"


@pytest.mark.asyncio
async def test_dispatcher_process_message_error_handling():
    """Tests that the dispatcher rejects invalid message bodies without invoking the use case."""
    fake_use_case = FakeProcessInboundEdiUseCase()

    async def fake_factory(tenant_id: str):
        return fake_use_case

    dispatcher = EdiComputeDispatcher(use_case_factory=fake_factory)

    # missing trace_id should be rejected before the use case runs
    message_body = {"s3_uri": "s3://edi/123.x12", "tenant_id": "1"}

    # Should not raise exception (InvalidMessageError is swallowed so message gets deleted)
    await dispatcher.dispatch_raw(message_body)

    # Use case should not have been called with invalid data
    assert fake_use_case.called_trace_id is None
