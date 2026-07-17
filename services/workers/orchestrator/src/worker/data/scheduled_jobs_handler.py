import logging
import uuid
from typing import Any

from scheduler.domain.models import Job

logger = logging.getLogger(__name__)


async def process_scheduled_job(message: dict[str, Any], **kwargs: Any) -> None:
    """
    Generic dispatcher for scheduled jobs.
    It requires a 'registry' to be passed in via **kwargs.
    """
    job_id = message.get("job_id")
    job_name = message.get("job_name")
    job_payload = message.get("payload", {})

    if not job_id or not job_name:
        logger.error(f"Missing job_id or job_name in message: {message}")
        return

    logger.info(f"Processing scheduled job: {job_name} ({job_id})")

    registry = kwargs.get("registry")
    if not registry:
        logger.error("JobHandlerRegistry not found in kwargs")
        return

    handler = registry.get(job_name)
    if not handler:
        logger.error(f"Unknown scheduled job name: {job_name}")
        return

    # Reconstruct a dummy Job object just enough for the handler to execute it
    job = Job(id=uuid.UUID(job_id), name=job_name, payload=job_payload)

    await handler.execute(job)
