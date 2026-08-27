import datetime
from abc import ABC, abstractmethod

from .models import Job


class JobHandlerPort(ABC):
    @abstractmethod
    async def execute(self, job: Job) -> datetime.datetime | None:
        """
        Process the scheduled job payload.
        Returns an optional datetime indicating when the job should next run.
        Returning None delegates next-run scheduling to the scheduler based on the job interval.
        """
        ...
