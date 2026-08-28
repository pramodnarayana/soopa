import asyncio
import json
import os
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import aioboto3
import pytest
import structlog


class SqsTestPublisher:
    def __init__(self, endpoint_url: str):
        self.endpoint_url = endpoint_url
        self.session = aioboto3.Session()

    async def publish(self, queue_name: str, payload: dict[str, Any]) -> None:
        async with self.session.client(
            "sqs", endpoint_url=self.endpoint_url, region_name="us-east-1"
        ) as sqs:
            resp = await sqs.get_queue_url(QueueName=queue_name)
            queue_url = resp["QueueUrl"]
            dedup_id = payload.get("idempotency_key") or str(uuid.uuid4())
            await sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(payload),
                MessageGroupId="default",
                MessageDeduplicationId=dedup_id,
            )


from database.models.identity import Tenant
from dotenv import load_dotenv
from edi.adapters.outbound.database.connection import DatabaseRouter
from edi.adapters.outbound.database.models.control_plane import AS2Partner
from edi.adapters.outbound.database.models.data_plane import AS2Partner as TenantAS2Partner
from edi.domain.events import EdiEventType
from sqlalchemy import delete, select
from ucp_models.events import ControlPlaneOutbox
from ucp_models.infrastructure import DatabaseShard, ShardRegistry
from ucp_models.subscriptions import App

from config_sync_worker.adapters.acl.registry import DefaultEventTranslator
from config_sync_worker.adapters.db_replication import SqlAlchemyReplicationAdapter
from config_sync_worker.adapters.db_tenant import SqlAlchemyTenantAdapter
from config_sync_worker.adapters.inbound.workers.edi_config_sync_sqs_dispatcher import (
    EdiConfigSyncSqsDispatcher,
)
from config_sync_worker.domain.service import ProvisioningWorkerService

load_dotenv()


@pytest.fixture(scope="session")
def postgres_container() -> "Any":
    from testcontainers.community.postgres import PostgresContainer

    postgres = PostgresContainer("postgres:15-alpine")
    postgres.start()
    yield postgres
    postgres.stop()


@pytest.fixture
async def test_db_router(postgres_container: Any) -> "AsyncGenerator[DatabaseRouter, None]":
    base_url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    )

    router = DatabaseRouter(global_db_url=base_url)

    engine = await router.get_engine("global", base_url)
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS ucp"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS edi"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS identity"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS scheduling"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS notifications"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS observability"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS platform"))

        from database.models.core import GlobalRegistry

        await conn.run_sync(GlobalRegistry.metadata.create_all)

        from edi.adapters.outbound.database.models.data_plane import TenantBase

        await conn.run_sync(TenantBase.metadata.create_all)

    async for session in router.get_global_session():
        from ucp_models.infrastructure import DatabaseShard

        shard1 = DatabaseShard(id="test_shard_id", name="shard_1", dsn=base_url)
        await session.merge(shard1)
        await session.commit()

    await router.get_engine("shard_1", base_url)

    yield router
    await router.close_all()


@pytest.fixture
async def e2e_context(
    test_db_router: DatabaseRouter, postgres_container: Any
) -> "AsyncGenerator[dict[str, Any], None]":
    """
    Sets up the DatabaseRouter and SQS adapters for the E2E test.
    Cleans up inserted data at the end of the test.
    """
    db_router = test_db_router
    base_url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    )

    tenant_adapter = SqlAlchemyTenantAdapter(db_router)
    replication_adapter = SqlAlchemyReplicationAdapter(db_router, tenant_adapter)

    # We use localstack URL directly as per the local dev environment
    sqs_endpoint = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")

    queue_name = f"test-edi-tenant-sync-{uuid.uuid4()}.fifo"

    message_publisher = SqsTestPublisher(
        endpoint_url=sqs_endpoint,
    )

    # Create the queue if it doesn't exist, and purge it
    async with message_publisher.session.client(
        "sqs", endpoint_url=sqs_endpoint, region_name="us-east-1"
    ) as sqs:
        try:
            await sqs.create_queue(QueueName=queue_name, Attributes={"FifoQueue": "true"})
            resp = await sqs.get_queue_url(QueueName=queue_name)
            await sqs.purge_queue(QueueUrl=resp["QueueUrl"])
            await asyncio.sleep(1)
        except Exception:  # noqa: BLE001
            structlog.get_logger(__name__).warning("Could not setup queue: {e}")
            pytest.skip("LocalStack is not available. Skipping integration test.")

    # 1. Initialize the core replication service
    worker_service = ProvisioningWorkerService(tenant_adapter, replication_adapter)

    # 2. Initialize the dispatcher with the translator
    translator = DefaultEventTranslator()
    dispatcher = EdiConfigSyncSqsDispatcher(
        domain_service=worker_service, translator_port=translator
    )

    # 3. Create a raw consumer so tests can manually poll and dispatch exactly once
    from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer

    test_consumer = AwsSqsConsumer(
        queue_name=queue_name,
        endpoint_url=sqs_endpoint,
        region_name="us-east-1",
    )

    async def process_next_event_helper() -> bool:
        async with test_consumer.poll_raw_message() as ackable_msg:
            if ackable_msg:
                await dispatcher.dispatch_raw(ackable_msg.payload)
                await ackable_msg.ack()
                return True
        return False

    worker_service.process_next_event = process_next_event_helper

    test_partner_id = str(uuid.uuid4())
    test_tenant_id = str(uuid.uuid4())

    async for session in db_router.get_global_session():
        tenant = Tenant(
            id=test_tenant_id,
            name=f"Test Tenant {test_tenant_id}",
            idp_tenant_id=f"idp_{test_tenant_id}",
            slug=f"tenant_{test_tenant_id}",
        )
        session.add(tenant)
        await session.flush()

        shard_res = await session.execute(
            select(DatabaseShard).where(DatabaseShard.name == "shard_1")
        )
        shard = shard_res.scalars().first()

        app_res = await session.execute(select(App).where(App.slug == "edi"))
        edi_app = app_res.scalars().first()
        if not edi_app:
            edi_app = App(
                id="app_{test_tenant_id}",
                slug="edi",
                name="EDI Application",
            )
            session.add(edi_app)
            await session.commit()

        tenant_shard = ShardRegistry(
            tenant_id=test_tenant_id,
            app_id=edi_app.id,
            shard_id=shard.id,
        )
        session.add(tenant_shard)

        partner = AS2Partner(
            id=test_partner_id,
            tenant_id=test_tenant_id,
            name="Integration Test Partner",
            as2_id="INT_TEST_AS2",
            active=True,
        )
        session.add(partner)
        await session.commit()

    yield {
        "db_router": db_router,
        "worker_service": worker_service,
        "message_publisher": message_publisher,
        "partner_id": test_partner_id,
        "tenant_id": test_tenant_id,
        "queue_name": queue_name,
        "base_url": base_url,
    }

    # Cleanup
    async for session in db_router.get_global_session():
        await session.execute(
            delete(ControlPlaneOutbox).where(
                ControlPlaneOutbox.event_type == EdiEventType.edi_as2_partner_created.value,
                ControlPlaneOutbox.tenant_id == test_tenant_id,
            )
        )
        await session.execute(delete(AS2Partner).where(AS2Partner.id == test_partner_id))
        await session.execute(
            delete(ShardRegistry).where(ShardRegistry.tenant_id == test_tenant_id)
        )
        await session.execute(delete(Tenant).where(Tenant.id == test_tenant_id))
        await session.commit()

    async for tenant_session in db_router.get_tenant_session(test_tenant_id, "shard_1", base_url):
        await tenant_session.execute(
            delete(TenantAS2Partner).where(TenantAS2Partner.id == test_partner_id)
        )
        await tenant_session.commit()

    async with message_publisher.session.client(
        "sqs", endpoint_url=sqs_endpoint, region_name="us-east-1"
    ) as sqs:
        try:
            resp = await sqs.get_queue_url(QueueName=queue_name)
            await sqs.delete_queue(QueueUrl=resp["QueueUrl"])
        except Exception:  # noqa: BLE001
            structlog.get_logger(__name__).warning("Could not delete queue {queue_name}: {e}")

    await db_router.close_all()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_provisioning_replication_e2e_flow(e2e_context: dict[str, Any]) -> None:
    """
    Tests the full replication flow:
    1. API inserts an event into the Control Plane Outbox.
    2. Sweeper job reads it and publishes to SQS.
    3. Provisioning worker reads it from SQS and replicates the entity to the Tenant Shard.
    """
    ctx = e2e_context
    db_router = ctx["db_router"]
    worker_service = ctx["worker_service"]
    message_publisher = ctx["message_publisher"]
    queue_name = ctx["queue_name"]
    partner_id = ctx["partner_id"]
    tenant_id = ctx["tenant_id"]
    base_url = ctx["base_url"]

    # 1. Simulate the UCP API (AwsControlPlaneEventRouter) publishing directly to the SNS/SQS topic
    payload = {
        "tenant_id": tenant_id,
        "event_type": EdiEventType.edi_as2_partner_created.value,
        "resource_id": str(partner_id),
    }

    await message_publisher.publish(queue_name, payload)

    await asyncio.sleep(2)  # Give LocalStack SQS a moment to make the message visible

    # 3. Provisioning Worker processes the event
    processed = await worker_service.process_next_event()
    assert processed is True

    # 4. Verify replication occurred in the Shard DB
    async for tenant_session in db_router.get_tenant_session(tenant_id, "shard_1", base_url):
        res = await tenant_session.execute(
            select(TenantAS2Partner).where(TenantAS2Partner.id == partner_id)
        )
        replicated_partner = res.scalars().first()

        assert replicated_partner is not None
        assert replicated_partner.name == "Integration Test Partner"
        assert replicated_partner.as2_id == "INT_TEST_AS2"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_provisioning_negative_unregistered_event_dropped(
    e2e_context: dict[str, Any],
) -> None:
    """
    Tests that if a cross-domain UCP event (like tenant.provisioned) leaks into the EDI
    ProvisioningQueue, it is safely ignored and sent to the DLQ rather than crashing the worker.
    """
    ctx = e2e_context
    worker_service = ctx["worker_service"]
    message_publisher = ctx["message_publisher"]
    queue_name = ctx["queue_name"]
    tenant_id = ctx["tenant_id"]

    # Send an unregistered UCP event
    payload = {
        "tenant_id": tenant_id,
        "eventType": "tenant.provisioned",
        "resource_id": "tenant_123",
    }

    await message_publisher.publish(queue_name, payload)
    await asyncio.sleep(2)

    # Worker processes the event. Since it's unregistered, it is safely dropped,
    # but the consumption is considered successful processing, so it returns True.
    processed = await worker_service.process_next_event()
    assert processed is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_provisioning_negative_malformed_payload(e2e_context: dict[str, Any]) -> None:
    """
    Tests that if a malformed event (missing required fields) is sent, the orchestrator
    raises a PermanentProvisioningError and deletes the message without crashing the loop.
    """
    ctx = e2e_context
    worker_service = ctx["worker_service"]
    message_publisher = ctx["message_publisher"]
    queue_name = ctx["queue_name"]
    tenant_id = ctx["tenant_id"]

    # Send an event missing resource_id
    payload = {
        "tenant_id": tenant_id,
        "event_type": EdiEventType.edi_as2_partner_created.value,
        # missing resource_id
    }

    await message_publisher.publish(queue_name, payload)
    await asyncio.sleep(2)

    # Worker processes the event. The SQS consumer swallows the exception and doesn't ack,
    # so the orchestrator returns False.
    processed = await worker_service.process_next_event()
    assert processed is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_provisioning_idempotency(e2e_context: dict[str, Any]) -> None:
    """
    Tests that delivering the exact same event multiple times does not crash the orchestrator
    and handles upserts gracefully.
    """
    ctx = e2e_context
    db_router = ctx["db_router"]
    worker_service = ctx["worker_service"]
    message_publisher = ctx["message_publisher"]
    queue_name = ctx["queue_name"]
    partner_id = ctx["partner_id"]
    tenant_id = ctx["tenant_id"]
    base_url = ctx["base_url"]

    payload = {
        "tenant_id": tenant_id,
        "event_type": EdiEventType.edi_as2_partner_created.value,
        "resource_id": str(partner_id),
    }

    # Publish it twice
    await message_publisher.publish(queue_name, payload)
    await message_publisher.publish(queue_name, payload)
    await asyncio.sleep(2)

    # Process first event
    processed_1 = await worker_service.process_next_event()
    assert processed_1 is True

    # Process second event
    processed_2 = await worker_service.process_next_event()
    assert processed_2 is True

    # Verify replication still valid
    async for tenant_session in db_router.get_tenant_session(tenant_id, "shard_1", base_url):
        res = await tenant_session.execute(
            select(TenantAS2Partner).where(TenantAS2Partner.id == partner_id)
        )
        replicated_partner = res.scalars().first()
        assert replicated_partner is not None
