import logging
from typing import Any

logger = logging.getLogger(__name__)


class JobHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, Any] = {}

    def register(self, job_name: str, handler: Any) -> None:
        self._handlers[job_name] = handler
        logger.info(f"Registered job handler for {job_name}")

    def get(self, job_name: str) -> Any | None:
        return self._handlers.get(job_name)
