import logging

from ...domain.models import ScheduledJob
from ...ports.job_dispatcher import JobDispatcherPort

logger = logging.getLogger(__name__)


class DummyJobDispatcher(JobDispatcherPort):
    """
    Temporary JobDispatcher that logs the dispatch.
    To be replaced by SQSJobDispatcher or WebhookJobDispatcher.
    """

    async def dispatch(self, job: ScheduledJob) -> None:
        logger.info(
            f"Dummy dispatch: successfully published job {job.name} ({job.id}) to target_queue {job.target_queue}"
        )
