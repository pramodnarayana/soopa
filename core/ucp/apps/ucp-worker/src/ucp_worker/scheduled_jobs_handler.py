from typing import cast

import structlog
from pydantic import BaseModel, Field, ValidationError
from seedwork.domain.types import JsonDict

from ucp_worker.core.job_registry import JobHandlerRegistry
from ucp_worker.core.scheduler.models import Job

logger = structlog.get_logger(__name__)


class ScheduledJobMessage(BaseModel):
    job_id: str
    job_name: str
    payload: JsonDict = Field(default_factory=dict)
    correlation_id: str | None = None


async def process_scheduled_job(message: JsonDict, **kwargs: object) -> None:
    """
    Generic dispatcher for scheduled jobs.
    It requires a 'registry' to be passed in via **kwargs.
    """
    try:
        job_msg = ScheduledJobMessage.model_validate(message)
    except ValidationError:
        logger.exception(
            "invalid_scheduled_job_message",
            available_keys=list(message.keys()),
            correlation_id=message.get("correlation_id"),
        )
        return

    job_id = job_msg.job_id
    job_name = job_msg.job_name
    job_payload = job_msg.payload

    logger.info("processing_scheduled_job", job_name=job_name, job_id=job_id)

    registry = cast(JobHandlerRegistry | None, kwargs.get("registry"))
    if not registry:
        logger.error("job_handler_registry_missing_in_kwargs")
        return

    handler = registry.get(job_name)
    if not handler:
        logger.error("unknown_scheduled_job_name", job_name=job_name)
        raise ValueError(f"Unknown scheduled job name: {job_name}")

    # Reconstruct a dummy Job object just enough for the handler to execute it
    job = Job(id=job_id, name=job_name, payload=job_payload)

    await handler.execute(job)
