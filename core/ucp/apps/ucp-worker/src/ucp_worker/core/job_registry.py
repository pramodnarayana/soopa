from ucp_worker.core.scheduler.handler import JobHandlerPort


class JobHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandlerPort] = {}

    def register(self, job_name: str, handler: JobHandlerPort) -> None:
        self._handlers[job_name] = handler

    def get(self, job_name: str) -> JobHandlerPort | None:
        return self._handlers.get(job_name)
