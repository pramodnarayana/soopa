import abc
import datetime

from scheduler.domain.models import Job


class JobHandlerPort(abc.ABC):
    @abc.abstractmethod
    async def execute(self, job: Job) -> datetime.datetime | None:
        """Execute the job. Return a datetime to reschedule it, or None to complete it."""
        pass
