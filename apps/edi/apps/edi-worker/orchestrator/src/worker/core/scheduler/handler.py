from abc import ABC, abstractmethod

from .models import Job

class JobHandlerPort(ABC):
    @abstractmethod
    async def handle(self, job: Job) -> None:
        """Process the scheduled job payload."""
        pass
