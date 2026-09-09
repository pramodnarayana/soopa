from typing import Protocol


class JobHandler(Protocol):
    async def __call__(self, *args: object, **kwargs: object) -> object: ...


class JobHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_name: str, handler: JobHandler) -> None:
        self._handlers[job_name] = handler

    def get(self, job_name: str) -> JobHandler | None:
        return self._handlers.get(job_name)
