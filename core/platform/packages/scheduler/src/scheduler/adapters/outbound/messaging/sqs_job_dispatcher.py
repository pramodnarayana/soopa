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

    def __init__(self, endpoint_url: str | None = None, region: str = "us-east-1"):
        self.endpoint_url = endpoint_url
        self.region = region
        self.session = aioboto3.Session()
        self._queue_url_cache: dict[str, str] = {}

    async def dispatch(self, job: ScheduledJob) -> None:
        if not job.target_queue:
            logger.warning("sqs_dispatcher_no_target_queue", job_id=job.id, job_name=job.name)
            return

        async with self.session.client(
            "sqs", endpoint_url=self.endpoint_url, region_name=self.region
        ) as sqs:
            if job.target_queue not in self._queue_url_cache:
                resp = await sqs.get_queue_url(QueueName=job.target_queue)
                self._queue_url_cache[job.target_queue] = resp["QueueUrl"]

            queue_url = self._queue_url_cache[job.target_queue]

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
