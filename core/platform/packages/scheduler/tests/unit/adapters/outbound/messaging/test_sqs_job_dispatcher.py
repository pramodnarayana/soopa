import json
from datetime import UTC, datetime

import pytest

from scheduler.adapters.outbound.messaging.sqs_job_dispatcher import SQSJobDispatcher
from scheduler.domain.constants import JobStatus
from scheduler.domain.scheduled_job import ScheduledJob


class FakeSqsClient:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, str]] = []

    async def __aenter__(self) -> "FakeSqsClient":
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        pass

    async def send_message(self, **kwargs: str) -> dict[str, object]:
        self.sent_messages.append(kwargs)
        return {"MessageId": "msg-123"}


class FakeAioBoto3Session:
    def __init__(self, client: FakeSqsClient) -> None:
        self.fake_client = client

    def client(
        self,
        service_name: str,
        *,
        endpoint_url: str | None = None,
        region_name: str | None = None,
    ) -> FakeSqsClient:
        return self.fake_client


@pytest.mark.asyncio
async def test_sqs_job_dispatcher_missing_target_queue_returns_early() -> None:
    client = FakeSqsClient()
    session = FakeAioBoto3Session(client)
    dispatcher = SQSJobDispatcher(
        queue_url_map={"q1": "http://sqs.local/q1"},
        session=session,
    )

    job = ScheduledJob(
        id="job-1",
        name="test_job",
        target_queue=None,
        payload={},
        status=JobStatus.PENDING,
        cron_expression=None,
        interval_seconds=None,
        retry_count=0,
        max_retries=3,
        next_run_at=datetime.now(UTC),
    )

    await dispatcher.dispatch(job)
    assert len(client.sent_messages) == 0


@pytest.mark.asyncio
async def test_sqs_job_dispatcher_unmapped_queue_raises_value_error() -> None:
    client = FakeSqsClient()
    session = FakeAioBoto3Session(client)
    dispatcher = SQSJobDispatcher(
        queue_url_map={"q1": "http://sqs.local/q1"},
        session=session,
    )

    job = ScheduledJob(
        id="job-1",
        name="test_job",
        target_queue="unmapped_queue",
        payload={},
        status=JobStatus.PENDING,
        cron_expression=None,
        interval_seconds=None,
        retry_count=0,
        max_retries=3,
        next_run_at=datetime.now(UTC),
    )

    with pytest.raises(
        ValueError, match="Queue URL not configured for target queue: unmapped_queue"
    ):
        await dispatcher.dispatch(job)


@pytest.mark.asyncio
async def test_sqs_job_dispatcher_publishes_fifo_message() -> None:
    client = FakeSqsClient()
    session = FakeAioBoto3Session(client)
    dispatcher = SQSJobDispatcher(
        queue_url_map={"edi-jobs.fifo": "http://sqs.local/000000000000/edi-jobs.fifo"},
        session=session,
    )

    job = ScheduledJob(
        id="job-fifo-1",
        name="edi_sweep",
        target_queue="edi-jobs.fifo",
        payload={"batch": 50},
        status=JobStatus.PENDING,
        cron_expression=None,
        interval_seconds=None,
        retry_count=0,
        max_retries=3,
        next_run_at=datetime.now(UTC),
    )

    await dispatcher.dispatch(job)
    assert len(client.sent_messages) == 1
    sent = client.sent_messages[0]
    assert sent["QueueUrl"] == "http://sqs.local/000000000000/edi-jobs.fifo"
    assert sent["MessageGroupId"] == "edi_sweep"
    assert sent["MessageDeduplicationId"] == "job-fifo-1"

    body = json.loads(sent["MessageBody"])
    assert body["job_id"] == "job-fifo-1"
    assert body["job_name"] == "edi_sweep"
    assert body["payload"] == {"batch": 50}
