from typing import Any


class JobHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, Any] = {}

    def register(self, job_name: str, handler: Any) -> None:
        self._handlers[job_name] = handler

    def get(self, job_name: str) -> Any | None:
        return self._handlers.get(job_name)
