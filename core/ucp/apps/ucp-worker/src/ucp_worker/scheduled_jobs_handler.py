import uuid
from typing import Any

import structlog

from ucp_worker.core.scheduler.models import Job

logger = structlog.get_logger(__name__)


async def process_scheduled_job(message: dict[str, Any], **kwargs: Any) -> None:
    """
    Generic dispatcher for scheduled jobs.
    It requires a 'registry' to be passed in via **kwargs.
    """
    job_id = message.get("job_id")
    job_name = message.get("job_name")
    job_payload = message.get("payload", {})

    if not job_id or not job_name:
        logger.error("missing_job_identifier", raw_message=message)
        return

    logger.info("processing_scheduled_job", job_name=job_name, job_id=job_id)

    registry = kwargs.get("registry")
    if not registry:
        logger.error("job_handler_registry_missing_in_kwargs")
        return

    handler = registry.get(job_name)
    if not handler:
        logger.error("unknown_scheduled_job_name", job_name=job_name)
        raise ValueError(f"Unknown scheduled job name: {job_name}")

    # Reconstruct a dummy Job object just enough for the handler to execute it
    job = Job(id=uuid.UUID(job_id), name=job_name, payload=job_payload)

    await handler.execute(job)
