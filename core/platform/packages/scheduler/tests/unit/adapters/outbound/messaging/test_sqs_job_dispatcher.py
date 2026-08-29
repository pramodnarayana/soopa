import dataclasses
import json
from unittest.mock import AsyncMock, patch

import pytest

from scheduler.adapters.outbound.messaging.sqs_job_dispatcher import SQSJobDispatcher
from scheduler.domain.models import ScheduledJob


@pytest.fixture
def mock_job():
    return ScheduledJob(
        id="job-123",
        name="test-job",
        status="PENDING",
        cron_expression=None,
        interval_seconds=None,
        retry_count=0,
        max_retries=3,
        next_run_at=None,
        target_queue="test-queue",
        payload={"foo": "bar"},
    )


@pytest.mark.asyncio
async def test_sqs_job_dispatcher_no_target_queue():
    dispatcher = SQSJobDispatcher()
    job = ScheduledJob(
        id="job-123",
        name="test-job",
        status="PENDING",
        cron_expression=None,
        interval_seconds=None,
        retry_count=0,
        max_retries=3,
        next_run_at=None,
        target_queue=None,
        payload={},
    )
    # Should return early without raising
    await dispatcher.dispatch(job)


@pytest.mark.asyncio
@patch("scheduler.adapters.outbound.messaging.sqs_job_dispatcher.aioboto3.Session")
async def test_sqs_job_dispatcher_success(mock_session_cls, mock_job):
    mock_session = mock_session_cls.return_value
    mock_sqs_client = AsyncMock()
    mock_session.client.return_value.__aenter__.return_value = mock_sqs_client

    mock_sqs_client.get_queue_url.return_value = {"QueueUrl": "https://sqs/test-queue"}

    dispatcher = SQSJobDispatcher()
    await dispatcher.dispatch(mock_job)

    mock_sqs_client.get_queue_url.assert_awaited_once_with(QueueName="test-queue")
    mock_sqs_client.send_message.assert_awaited_once_with(
        QueueUrl="https://sqs/test-queue",
        MessageBody=json.dumps(
            {"job_id": "job-123", "job_name": "test-job", "payload": {"foo": "bar"}}
        ),
    )

    # Second dispatch uses cache
    await dispatcher.dispatch(mock_job)
    assert mock_sqs_client.get_queue_url.call_count == 1


@pytest.mark.asyncio
@patch("scheduler.adapters.outbound.messaging.sqs_job_dispatcher.aioboto3.Session")
async def test_sqs_job_dispatcher_fifo(mock_session_cls, mock_job):
    mock_session = mock_session_cls.return_value
    mock_sqs_client = AsyncMock()
    mock_session.client.return_value.__aenter__.return_value = mock_sqs_client

    mock_job = dataclasses.replace(mock_job, target_queue="test-queue.fifo")
    mock_sqs_client.get_queue_url.return_value = {"QueueUrl": "https://sqs/test-queue.fifo"}

    dispatcher = SQSJobDispatcher()
    await dispatcher.dispatch(mock_job)

    mock_sqs_client.send_message.assert_awaited_once_with(
        QueueUrl="https://sqs/test-queue.fifo",
        MessageBody=json.dumps(
            {"job_id": "job-123", "job_name": "test-job", "payload": {"foo": "bar"}}
        ),
        MessageGroupId="test-job",
        MessageDeduplicationId="job-123",
    )
