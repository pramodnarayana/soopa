import structlog

from scheduler.domain.models import ScheduledJob
from scheduler.ports.job_dispatcher_port import JobDispatcherPort

logger = structlog.get_logger(__name__)


class DummyJobDispatcher(JobDispatcherPort):
    """
    Temporary JobDispatcher that logs the dispatch.
    To be replaced by SQSJobDispatcher or WebhookJobDispatcher.
    """

    async def dispatch(self, job: ScheduledJob) -> None:
        logger.info(
            "Dummy dispatch: successfully published job {job.name} ({job.id}) to target_queue {job.target_queue}",
            job_name=job.name,
            job_id=job.id,
            job_target_queue=job.target_queue,
        )
