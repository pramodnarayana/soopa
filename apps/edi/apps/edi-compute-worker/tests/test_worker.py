import json

import pytest
from edi.adapters.outbound.transformer.domain.models import ParsedEdiPayload

from compute_worker.worker import SQSComputeWorker


class FakeProcessInboundEdiUseCase:
    def __init__(self):
        self.called_trace_id = None
        self.called_s3_uri = None

    async def execute(
        self, trace_id: str, standard: str = "X12", transaction_type: str = "UNKNOWN"
    ) -> ParsedEdiPayload:
        self.called_trace_id = trace_id
        self.called_standard = standard
        self.called_transaction_type = transaction_type

        # We can raise an error if trace_id is empty to test error handling
        if not trace_id or trace_id == "unknown":
            raise ValueError("Invalid trace ID")

        return ParsedEdiPayload(
            sender_id="TEST", receiver_id="TEST", interchange_control_number="1", transactions=[]
        )


class FakeSQSClient:
    """Fake SQS client with delete_message capability."""

    def __init__(self):
        self.deleted_queue_url = None
        self.deleted_receipt_handle = None

    async def delete_message(self, QueueUrl: str, ReceiptHandle: str) -> None:
        self.deleted_queue_url = QueueUrl
        self.deleted_receipt_handle = ReceiptHandle


@pytest.mark.asyncio
async def test_worker_process_message_success():
    """Tests that the worker parses SQS payload and routes it to the use case."""
    fake_use_case = FakeProcessInboundEdiUseCase()

    async def fake_factory(trace_id: str):
        return fake_use_case

    worker = SQSComputeWorker(use_case_factory=fake_factory, queue_url="http://fake-queue")
    fake_sqs = FakeSQSClient()

    import json

    sqs_message = {
        "Body": json.dumps(
            {"trace_id": "trace-123", "tenant_id": "1", "s3_uri": "s3://edi/123.x12"}
        ),
        "ReceiptHandle": "fake-receipt-handle",
    }

    await worker._process_message(sqs_message, fake_sqs)

    assert fake_use_case.called_trace_id == "trace-123"

    assert fake_sqs.deleted_queue_url == "http://fake-queue"
    assert fake_sqs.deleted_receipt_handle == "fake-receipt-handle"


@pytest.mark.asyncio
async def test_worker_process_message_error_handling():
    """Tests that the worker rejects invalid message bodies without invoking the use case."""
    fake_use_case = FakeProcessInboundEdiUseCase()

    async def fake_factory(trace_id: str):
        return fake_use_case

    worker = SQSComputeWorker(use_case_factory=fake_factory, queue_url="http://fake-queue")
    fake_sqs = FakeSQSClient()

    # missing trace_id should be rejected before the use case runs
    sqs_message = {"Body": json.dumps({"s3_uri": "s3://edi/123.x12"})}

    # Should not raise exception (error is swallowed)
    await worker._process_message(sqs_message, fake_sqs)

    # Use case should not have been called with invalid data
    assert fake_use_case.called_trace_id is None


@pytest.mark.asyncio
async def test_worker_lifecycle():
    """Tests the start/stop state mutations of the worker."""
    fake_use_case = FakeProcessInboundEdiUseCase()

    async def fake_factory(trace_id: str):
        return fake_use_case

    worker = SQSComputeWorker(use_case_factory=fake_factory, queue_url="http://fake-queue")

    assert not worker._running

    # We test the stop method
    await worker.stop()
    assert not worker._running
