import json
from typing import Any

import aioboto3
import structlog

from scheduler.domain.models import ScheduledJob
from scheduler.ports.outbound.job_dispatcher_port import JobDispatcherPort

logger = structlog.get_logger(__name__)


class SQSJobDispatcher(JobDispatcherPort):
    """
    SQS-backed JobDispatcher that publishes scheduled jobs to their target SQS queues.
    """

    def __init__(
        self,
        queue_url_map: dict[str, str],
        endpoint_url: str | None = None,
        region: str = "us-east-1",
    ):
        self.queue_url_map = queue_url_map
        self.endpoint_url = endpoint_url
        self.region = region
        self.session = aioboto3.Session()

    async def dispatch(self, job: ScheduledJob) -> None:
        if not job.target_queue:
            logger.warning("sqs_dispatcher_no_target_queue", job_id=job.id, job_name=job.name)
            return

        queue_url = self.queue_url_map.get(job.target_queue)
        if not queue_url:
            raise ValueError(f"Queue URL not configured for target queue: {job.target_queue}")

        async with self.session.client(
            "sqs", endpoint_url=self.endpoint_url, region_name=self.region
        ) as sqs:
            payload = {"job_id": job.id, "job_name": job.name, "payload": job.payload}

            kwargs: dict[str, Any] = {
                "QueueUrl": queue_url,
                "MessageBody": json.dumps(payload),
            }
            if job.target_queue.endswith(".fifo"):
                kwargs["MessageGroupId"] = job.name
                kwargs["MessageDeduplicationId"] = job.id

            await sqs.send_message(**kwargs)
            logger.info("sqs_dispatcher_published", job_id=job.id, queue=job.target_queue)
