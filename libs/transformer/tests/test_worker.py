import json

import pytest
from transformer.domain.models import ParsedEdiPayload
from transformer.worker import SQSTransformerWorker


class FakeProcessInboundEdiUseCase:
    def __init__(self):
        self.called_trace_id = None
        self.called_s3_uri = None

    async def execute(self, trace_id: str, s3_uri: str) -> ParsedEdiPayload:
        self.called_trace_id = trace_id
        self.called_s3_uri = s3_uri

        # We can raise an error if trace_id is empty to test error handling
        if not trace_id or trace_id == "unknown":
            raise ValueError("Invalid trace ID")

        return ParsedEdiPayload(
            sender_id="TEST", receiver_id="TEST", interchange_control_number="1", transactions=[]
        )


@pytest.mark.asyncio
async def test_worker_process_message_success():
    """Tests that the worker parses SQS payload and routes it to the use case."""
    fake_use_case = FakeProcessInboundEdiUseCase()
    worker = SQSTransformerWorker(use_case=fake_use_case, queue_url="http://fake-queue")

    import json

    sqs_message = {"Body": json.dumps({"trace_id": "trace-123", "s3_uri": "s3://edi/123.x12"})}

    await worker._process_message(sqs_message)

    assert fake_use_case.called_trace_id == "trace-123"
    assert fake_use_case.called_s3_uri == "s3://edi/123.x12"


@pytest.mark.asyncio
async def test_worker_process_message_error_handling():
    """Tests that the worker swallows exceptions during message processing to prevent crashing."""
    fake_use_case = FakeProcessInboundEdiUseCase()
    worker = SQSTransformerWorker(use_case=fake_use_case, queue_url="http://fake-queue")

    # missing trace_id will cause FakeProcessInboundEdiUseCase to raise ValueError
    sqs_message = {"Body": json.dumps({"s3_uri": "s3://edi/123.x12"})}

    # Should not raise exception
    await worker._process_message(sqs_message)

    assert fake_use_case.called_trace_id == "unknown"


@pytest.mark.asyncio
async def test_worker_lifecycle():
    """Tests the start/stop state mutations of the worker."""
    fake_use_case = FakeProcessInboundEdiUseCase()
    worker = SQSTransformerWorker(use_case=fake_use_case, queue_url="http://fake-queue")

    assert not worker._running

    # We test the stop method
    await worker.stop()
    assert not worker._running
