from typing import Protocol

from scheduler.domain.scheduled_job import ScheduledJob


class JobDispatcherPort(Protocol):
    """
    Outbound port for dispatching a scheduled job to its target queue (e.g. SQS, Webhook).
    """

    async def dispatch(self, job: ScheduledJob) -> None: ...
