"""Pure zero-mock Phase 4 unit tests for SqlAlchemyJobRepository ORM mapper."""

from __future__ import annotations

from datetime import UTC, datetime

from database.models.scheduling import ScheduledJob as OrmScheduledJob
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id

from scheduler.adapters.outbound.database.sqlalchemy_job_repository import SqlAlchemyJobRepository
from scheduler.domain.constants import JobStatus


def test_sqlalchemy_job_repository_orm_to_domain_mapper() -> None:
    next_run = datetime.now(UTC)
    job_id = generate_id(SystemIdPrefix.JOB.value)

    orm_job = OrmScheduledJob(
        id=job_id,
        name="edi_outbox_sweeper",
        target_queue="https://sqs.us-east-1.amazonaws.com/000000000000/edi-jobs",
        payload={"batch_size": 100},
        status=JobStatus.RUNNING.value,
        cron_expression="*/5 * * * *",
        interval_seconds=None,
        retry_count=1,
        max_retries=5,
        next_run_at=next_run,
    )

    domain_job = SqlAlchemyJobRepository._to_domain_model(orm_job)
    assert domain_job.id == job_id
    assert domain_job.name == "edi_outbox_sweeper"
    assert domain_job.status == JobStatus.RUNNING
    assert domain_job.payload == {"batch_size": 100}
    assert domain_job.cron_expression == "*/5 * * * *"
    assert domain_job.interval_seconds is None
    assert domain_job.retry_count == 1
    assert domain_job.max_retries == 5
    assert domain_job.next_run_at == next_run
