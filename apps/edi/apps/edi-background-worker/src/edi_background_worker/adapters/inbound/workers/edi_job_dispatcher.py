from collections.abc import Awaitable, Callable
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Type alias for a simple async handler that accepts only the raw message dict.
_JobHandler = Callable[[dict[str, Any]], Awaitable[None]]


class EdiJobDispatcher:
    """
    Lightweight event dispatcher for EDI background worker jobs.
    Mirrors the identity-worker dispatcher: routes incoming SQS messages to
    the correct job handler by matching the `job_name` field.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, _JobHandler] = {}

    def subscribe(self, job_name: str, handler: _JobHandler) -> None:
        self._handlers[job_name] = handler

    async def dispatch(self, message: dict[str, Any]) -> None:
        job_name = message.get("job_name", "")
        handler = self._handlers.get(job_name)
        if handler is None:
            logger.error("edi_unknown_job_name", job_name=job_name)
            raise ValueError(f"Unknown EDI job name: {job_name}")
        await handler(message)
