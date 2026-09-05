import datetime
import json
import os
import uuid

import aioboto3
import pytest
from edi.testing.factories.outbox import DataPlaneOutboxBuilder
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from outbox.domain.constants import OutboxStatus

from edi_background_worker.adapters.outbound.database.postgres_edi_audit_log_cleanup_repository import (
    SqlAlchemyEdiAuditLogCleanupRepository,
)
from edi_background_worker.adapters.outbound.database.postgres_edi_data_plane_outbox_repository import (
    PostgresEdiDataPlaneOutboxRepository,
)

pytestmark = pytest.mark.integration


from database.router import DatabaseRouterPort


@pytest.mark.integration
async def test_sweeper_fetches_and_processes_events(db_router: DatabaseRouterPort):
    # 1. Setup Data - stuck events that need sweeping
    async for test_session in db_router.get_shard_session("ucp_shard_1", "mock_dsn"):
        builder = DataPlaneOutboxBuilder(session=test_session)
        # We will create events with default properties that makes them look "stuck".
        # e.g., in PROCESSING state but with lease expired (which happens when sweep_stuck_events runs).
        # Actually sweep_stuck_events resets them to PENDING so they can be claimed again.

        # We'll just create pending events to simulate they were swept and can now be published.
        # Note: the sweep stuck logic resets them, then the sweeper daemon claims them.
        event1 = await builder.create(event_type="TRANSFORM_EVENT", status=OutboxStatus.PROCESSING)
        event2 = await builder.create(event_type="DELIVER_EVENT", status=OutboxStatus.PROCESSING)

        # Manually force them to be "stuck" by setting lease_expires_at to the past

        event1.lease_expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            minutes=10
        )
        event2.lease_expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            minutes=10
        )

        await test_session.commit()

    # 2. Use real LocalStack SQS publisher
    sqs_endpoint = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
    # We will create a temporary queue for this test to ensure isolation
    queue_name = f"test-sweeper-{int(datetime.datetime.now().timestamp())}-{uuid.uuid4().hex}"

    async with aioboto3.Session().client(
        "sqs", endpoint_url=sqs_endpoint, region_name="us-east-1"
    ) as sqs:
        resp = await sqs.create_queue(QueueName=queue_name)
        queue_url = resp["QueueUrl"]

        try:
            from pubsub.aws.aws_sqs_publisher import AwsSqsPublisher

            real_publisher = AwsSqsPublisher(
                queue_url=queue_url,
                endpoint_url=sqs_endpoint,
                region_name="us-east-1",
            )

            repo = PostgresEdiDataPlaneOutboxRepository(db_router=db_router)

            use_case = OutboxSweeperUseCase(repository=repo, publisher=real_publisher)

            # 3. Execute Sweeper against real local DB and real LocalStack SQS
            await use_case.execute()

            # 4. Verify by authentically polling the real queue
            messages_received = []
            for _ in range(5):  # Poll a few times just in case
                resp = await sqs.receive_message(
                    QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=1
                )
                if "Messages" in resp:
                    messages_received.extend(resp["Messages"])
                if len(messages_received) >= 2:
                    break

            assert len(messages_received) >= 2

            # Validate payload actually contains outbox message contents
            bodies = [json.loads(m["Body"]) for m in messages_received]
            assert any("TRANSFORM_EVENT" in str(b) for b in bodies)
            assert any("DELIVER_EVENT" in str(b) for b in bodies)

        finally:
            await sqs.delete_queue(QueueUrl=queue_url)


@pytest.mark.integration
async def test_bounded_two_shard_cleanup_failure_propagates(
    db_router: DatabaseRouterPort, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = SqlAlchemyEdiAuditLogCleanupRepository(db_router=db_router)

    # Force a failure on shard_1 by patching db_router.get_shard_session
    original_get_shard_session = db_router.get_shard_session

    async def mock_get_all_shards():
        return [("ucp_shard_1", "mock_dsn_1"), ("ucp_shard_2", "mock_dsn_2")]

    monkeypatch.setattr(db_router, "get_all_shards", mock_get_all_shards)

    async def mock_fail_session(shard_name: str, dsn: str | None = None):
        if shard_name == "ucp_shard_1":
            raise RuntimeError("Database connection lost for shard_1")
        # Yield from original generator
        async for session in original_get_shard_session(shard_name, dsn):
            yield session

    monkeypatch.setattr(db_router, "get_shard_session", mock_fail_session)

    try:
        with pytest.raises(ExceptionGroup) as exc_info:
            await repo.cleanup_audit_logs(retention_days=30)

        # Verify grouped failure propagation
        assert "shard_cleanup_had_failures" in str(exc_info.value)
        assert len(exc_info.value.exceptions) == 1
        assert "Database connection lost for shard_1" in str(exc_info.value.exceptions[0])
    finally:
        monkeypatch.undo()
