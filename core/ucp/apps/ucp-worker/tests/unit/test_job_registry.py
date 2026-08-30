from ucp_worker.core.job_registry import JobHandlerRegistry
from ucp_worker.core.scheduler.handler import JobHandlerPort
from ucp_worker.core.scheduler.models import Job


class DummyJobHandler(JobHandlerPort):
    async def execute(self, job: Job) -> None:
        pass


def test_job_registry_register_and_get():
    registry = JobHandlerRegistry()
    handler = DummyJobHandler()

    assert registry.get("my_job") is None

    registry.register("my_job", handler)
    assert registry.get("my_job") is handler
