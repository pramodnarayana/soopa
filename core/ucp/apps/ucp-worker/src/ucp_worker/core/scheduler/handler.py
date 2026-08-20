from abc import ABC, abstractmethod
from datetime import datetime

from ucp_worker.core.scheduler.models import Job


class JobHandlerPort(ABC):
    @abstractmethod
    async def execute(self, job: Job) -> datetime | None:
        """
        Execute the job.
        Returns the next run time if it should be rescheduled manually,
        or None to let the scheduler handle it based on cron/interval.
        """
