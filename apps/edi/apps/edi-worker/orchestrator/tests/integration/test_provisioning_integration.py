import asyncio
import logging
import os
import uuid
from datetime import UTC, datetime

import pytest
from config.settings import get_settings
from database.connection import DatabaseRouter
from database.models.control_plane import AS2Partner, ControlPlaneOutbox
from database.models.data_plane import AS2Partner as TenantAS2Partner
from domain.events import ProvisioningEventType
from dotenv import load_dotenv
from sqlalchemy import delete, select

from worker.adapters.db_replication import SqlAlchemyReplicationAdapter
from worker.adapters.db_tenant import SqlAlchemyTenantAdapter
from worker.adapters.sqs_outbox import SqsOutboxAdapter
from worker.adapters.sqs_publisher import SqsPublisherAdapter
from worker.core.control_plane_outbox_relay import ControlPlaneOutboxRelayService
from worker.core.service import ProvisioningWorkerService

load_dotenv()
logging.basicConfig(level=logging.INFO)


@pytest.fixture
async def e2e_context():
    """
    Sets up the DatabaseRouter and SQS adapters for the E2E test.
    Cleans up inserted data at the end of the test.
    """
    settings = get_settings()
    db_router = DatabaseRouter(global_db_url=settings.database.global_url)

    tenant_adapter = SqlAlchemyTenantAdapter(db_router)
    replication_adapter = SqlAlchemyReplicationAdapter(db_router, tenant_adapter)

    # We use localstack URL directly as per the local dev environment
    sqs_endpoint = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")

    queue_name = "test-edi-tenant-sync.fifo"
    outbox_adapter = SqsOutboxAdapter(queue_name=queue_name)
    outbox_adapter.endpoint_url = sqs_endpoint

    message_publisher = SqsPublisherAdapter(
        endpoint_url=sqs_endpoint,
        region="us-east-1",
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
        except Exception as e:
            logging.warning(f"Could not setup queue: {e}")

    # Use a dedicated test queue so the integration test is isolated from production traffic.
    # Pass it to the handler constructor — no monkey-patching needed.
    worker_service = ProvisioningWorkerService(tenant_adapter, outbox_adapter, replication_adapter)
    sweeper_handler = ControlPlaneOutboxRelayService(
        db_router, message_publisher, queue_name=queue_name
    )

    test_partner_id = uuid.uuid4()
    test_tenant_id = str(uuid.uuid4())

    from database.models.control_plane import DatabaseShard, Tenant, TenantShard

    async for session in db_router.get_global_session():
        tenant = Tenant(id=test_tenant_id, name="Test Tenant")
        session.add(tenant)

        shard_res = await session.execute(
            select(DatabaseShard).where(DatabaseShard.name == "shard_1")
        )
        shard = shard_res.scalars().first()

        tenant_shard = TenantShard(
            tenant_id=test_tenant_id,
            shard_id=shard.id,
            shard_schema="tenant_" + test_tenant_id[:8],
            tier="standard",
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
        "sweeper_handler": sweeper_handler,
        "partner_id": test_partner_id,
        "tenant_id": test_tenant_id,
        "outbox_adapter": outbox_adapter,
    }

    # Cleanup
    async for session in db_router.get_global_session():
        await session.execute(
            delete(ControlPlaneOutbox).where(
                ControlPlaneOutbox.event_type == ProvisioningEventType.AS2_PARTNER_CREATED.value
            )
        )
        await session.execute(delete(AS2Partner).where(AS2Partner.id == test_partner_id))
        await session.execute(delete(TenantShard).where(TenantShard.tenant_id == test_tenant_id))
        await session.execute(delete(Tenant).where(Tenant.id == test_tenant_id))
        await session.commit()

    async for tenant_session in db_router.get_tenant_session(
        test_tenant_id,
        "shard_1",
        "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1",
    ):
        await tenant_session.execute(
            delete(TenantAS2Partner).where(TenantAS2Partner.id == test_partner_id)
        )
        await tenant_session.commit()

    await db_router.close_all()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_provisioning_replication_e2e_flow(e2e_context):
    """
    Tests the full replication flow:
    1. API inserts an event into the Control Plane Outbox.
    2. Sweeper job reads it and publishes to SQS.
    3. Provisioning worker reads it from SQS and replicates the entity to the Tenant Shard.
    """
    ctx = e2e_context
    db_router = ctx["db_router"]
    worker_service = ctx["worker_service"]
    sweeper_handler = ctx["sweeper_handler"]
    partner_id = ctx["partner_id"]
    tenant_id = ctx["tenant_id"]

    # 1. API creates an event in the outbox — event_type lives on the outbox row,
    #    NOT in the payload dict. The sweeper is responsible for injecting it into
    #    the SQS message body. Writing it here would mask the publisher contract.
    event_id = uuid.uuid4()
    async for session in db_router.get_global_session():
        outbox_event = ControlPlaneOutbox(
            id=event_id,
            tenant_id=tenant_id,
            idempotency_key=uuid.uuid4(),
            event_type=ProvisioningEventType.AS2_PARTNER_CREATED.value,
            payload={"tenant_id": tenant_id, "resource_id": str(partner_id)},
            status="PENDING",
            created_at=datetime.now(UTC),
        )
        session.add(outbox_event)
        await session.commit()

    # 2. Sweeper runs
    await sweeper_handler.relay_pending_events()
    async for session in db_router.get_global_session():
        res = await session.execute(
            select(ControlPlaneOutbox).where(ControlPlaneOutbox.id == event_id)
        )
        swept_event = res.scalars().first()
        assert swept_event is not None
        assert swept_event.status == "PROCESSED"

    await asyncio.sleep(2)  # Give LocalStack SQS a moment to make the message visible

    # 3. Provisioning Worker processes the event
    processed = await worker_service.process_next_event()
    assert processed is True

    # 4. Verify replication occurred in the Shard DB
    async for tenant_session in db_router.get_tenant_session(
        tenant_id, "shard_1", "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1"
    ):
        res = await tenant_session.execute(
            select(TenantAS2Partner).where(TenantAS2Partner.id == partner_id)
        )
        replicated_partner = res.scalars().first()

        assert replicated_partner is not None
        assert replicated_partner.name == "Integration Test Partner"
        assert replicated_partner.as2_id == "INT_TEST_AS2"
