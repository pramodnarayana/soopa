from scheduler.domain.models import ScheduledJob
from scheduler.ports.outbound.job_dispatcher_port import JobDispatcherPort


class FakeJobDispatcher(JobDispatcherPort):
    def __init__(self) -> None:
        self.dispatched_jobs: list[ScheduledJob] = []
        self.should_fail = False

    async def dispatch(self, job: ScheduledJob) -> None:
        if self.should_fail:
            raise ValueError("Fake dispatch failure")
        self.dispatched_jobs.append(job)
