import pytest
from pydantic import ValidationError

from ucp_worker.scheduled_jobs_handler import ScheduledJobMessage


@pytest.mark.parametrize("field", ["job_id", "job_name"])
def test_scheduled_job_message_rejects_empty_identifiers(field: str) -> None:
    message = {"job_id": "job-1", "job_name": "cleanup"}
    message[field] = ""

    with pytest.raises(ValidationError):
        ScheduledJobMessage.model_validate(message)


def test_scheduled_job_message_accepts_non_empty_identifiers() -> None:
    message = ScheduledJobMessage(job_id="job-1", job_name="cleanup")

    assert message.job_id == "job-1"
    assert message.job_name == "cleanup"
