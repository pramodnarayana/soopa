import json

import aioboto3
import structlog
from scheduler.domain.models import ScheduledJob
from scheduler.ports.outbound.job_dispatcher_port import JobDispatcherPort

logger = structlog.get_logger(__name__)


class SqsJobDispatcher(JobDispatcherPort):
    """Publish scheduled jobs to the SQS queue selected by the job definition."""

    def __init__(self, endpoint_url: str | None = None, region_name: str = "us-east-1") -> None:
        self.endpoint_url = endpoint_url
        self.region_name = region_name

    async def dispatch(self, job: ScheduledJob) -> None:
        if not job.target_queue:
            raise ValueError(f"No target_queue defined for job {job.name}")

        client_kwargs = {"region_name": self.region_name}
        if self.endpoint_url:
            client_kwargs["endpoint_url"] = self.endpoint_url

        session = aioboto3.Session()
        async with session.client("sqs", **client_kwargs) as sqs:
            queue_url_response = await sqs.get_queue_url(QueueName=job.target_queue)
            await sqs.send_message(
                QueueUrl=queue_url_response["QueueUrl"],
                MessageBody=json.dumps(
                    {
                        "job_id": job.id,
                        "job_name": job.name,
                        "payload": job.payload,
                    }
                ),
            )

        logger.info(
            "scheduled_job_dispatched",
            job_id=job.id,
            job_name=job.name,
            target_queue=job.target_queue,
        )
