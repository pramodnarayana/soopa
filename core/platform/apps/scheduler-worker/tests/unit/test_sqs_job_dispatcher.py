import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from scheduler.domain.models import ScheduledJob

from scheduler_worker.adapters.outbound.messaging.sqs_job_dispatcher import SqsJobDispatcher
from scheduler_worker.bootstrap.container import Container


def test_container_wires_sqs_job_dispatcher() -> None:
    container = Container(session_factory=MagicMock())

    assert isinstance(container.job_dispatcher(), SqsJobDispatcher)


@pytest.mark.asyncio
async def test_dispatches_job_to_edi_orchestrator_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    sqs = AsyncMock()
    sqs.get_queue_url.return_value = {"QueueUrl": "http://sqs/edi-orchestrator-jobs"}
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=sqs)
    client_context.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.client.return_value = client_context
    monkeypatch.setattr(
        "scheduler_worker.adapters.outbound.messaging.sqs_job_dispatcher.aioboto3.Session",
        lambda: session,
    )

    job = ScheduledJob(
        id="job-1",
        name="EDI_AUDIT_LOG_CLEANUP",
        target_queue="edi-orchestrator-jobs",
        payload={"retention_days": 90},
        status="RUNNING",
        cron_expression="0 2 * * *",
        interval_seconds=None,
        retry_count=0,
        max_retries=3,
        next_run_at=datetime.now(UTC),
    )

    await SqsJobDispatcher(endpoint_url="http://localstack:4566").dispatch(job)

    session.client.assert_called_once_with(
        "sqs", region_name="us-east-1", endpoint_url="http://localstack:4566"
    )
    sqs.get_queue_url.assert_awaited_once_with(QueueName="edi-orchestrator-jobs")
    sent = sqs.send_message.await_args.kwargs
    assert sent["QueueUrl"] == "http://sqs/edi-orchestrator-jobs"
    assert json.loads(sent["MessageBody"]) == {
        "job_id": "job-1",
        "job_name": "EDI_AUDIT_LOG_CLEANUP",
        "payload": {"retention_days": 90},
    }
