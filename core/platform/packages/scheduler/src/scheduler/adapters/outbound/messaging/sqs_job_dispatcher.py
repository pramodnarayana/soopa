import json
from typing import Protocol, runtime_checkable

import aioboto3
import structlog

from scheduler.domain.scheduled_job import ScheduledJob
from scheduler.ports.outbound.job_dispatcher_port import JobDispatcherPort

logger = structlog.get_logger(__name__)


@runtime_checkable
class SqsClientProtocol(Protocol):
    async def send_message(self, **kwargs: str) -> dict[str, object]: ...


@runtime_checkable
class SqsClientContextProtocol(Protocol):
    async def __aenter__(self) -> SqsClientProtocol: ...
    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None: ...


@runtime_checkable
class SqsSessionProtocol(Protocol):
    def client(
        self,
        service_name: str,
        *,
        endpoint_url: str | None = None,
        region_name: str | None = None,
    ) -> SqsClientContextProtocol: ...


class SQSJobDispatcher(JobDispatcherPort):
    """
    SQS-backed JobDispatcher that publishes scheduled jobs to their target SQS queues.
    """

    def __init__(
        self,
        queue_url_map: dict[str, str],
        endpoint_url: str | None = None,
        region: str = "us-east-1",
        session: SqsSessionProtocol | None = None,
    ):
        self.queue_url_map = queue_url_map
        self.endpoint_url = endpoint_url
        self.region = region
        self.session: SqsSessionProtocol = session or aioboto3.Session()

    async def dispatch(self, job: ScheduledJob) -> None:
        if not job.target_queue:
            logger.error("sqs_dispatcher_missing_target_queue", job_id=job.id, job_name=job.name)
            return

        queue_url = self.queue_url_map.get(job.target_queue)
        if not queue_url:
            raise ValueError(f"Queue URL not configured for target queue: {job.target_queue}")

        async with self.session.client(
            "sqs", endpoint_url=self.endpoint_url, region_name=self.region
        ) as sqs:
            payload = {"job_id": job.id, "job_name": job.name, "payload": job.payload}

            kwargs: dict[str, str] = {
                "QueueUrl": queue_url,
                "MessageBody": json.dumps(payload),
            }
            if job.target_queue.endswith(".fifo"):
                kwargs["MessageGroupId"] = job.name
                kwargs["MessageDeduplicationId"] = job.id

            await sqs.send_message(**kwargs)
            logger.info("sqs_dispatcher_published", job_id=job.id, queue=job.target_queue)
