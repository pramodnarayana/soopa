import abc

from scheduler.domain.models import Job


class JobHandlerPort(abc.ABC):
    @abc.abstractmethod
    async def execute(self, job: Job) -> None:
        """Execute the job. Handlers should raise exceptions on failure."""
        pass
