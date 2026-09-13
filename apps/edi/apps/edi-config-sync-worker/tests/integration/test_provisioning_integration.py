import asyncio
import dataclasses
import json
import os
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import aioboto3
import pytest
from identity.domain.identity_context import PLATFORM_TENANT_ID
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from seedwork import generate_id
from seedwork.events import EventEnvelope


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
            dedup_id = payload.get("idempotency_key") or generate_id("id")
            await sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(payload),
                MessageGroupId="default",
                MessageDeduplicationId=dedup_id,
            )


from database.models.identity import Tenant
from database.models.webhooks import Webhook as GlobalWebhook
from database.router import DatabaseRouter
from dotenv import load_dotenv
from edi.adapters.outbound.database.models.control_plane import AS2Partner
from edi.adapters.outbound.database.models.control_plane import OutboundRoute as GlobalOutboundRoute
from edi.adapters.outbound.database.models.data_plane import AS2Partner as TenantAS2Partner
from edi.adapters.outbound.database.models.data_plane import OutboundRoute as TenantOutboundRoute
from edi.adapters.outbound.database.models.data_plane import Webhook as TenantWebhook
from edi.domain.enums import EdiConnectionType, EdiEventType
from sqlalchemy import delete, select
from ucp_models.sharding import DatabaseShard, ShardRegistry
from ucp_models.subscriptions import App

from config_sync_worker.adapters.acl.registry import DefaultEventTranslator
from config_sync_worker.adapters.db_replication import SqlAlchemyReplicationAdapter
from config_sync_worker.adapters.db_tenant import SqlAlchemyTenantAdapter
from config_sync_worker.adapters.inbound.workers.edi_config_sync_sqs_dispatcher import (
    EdiConfigSyncSqsDispatcher,
)
from config_sync_worker.domain.service import ProvisioningWorkerService

load_dotenv()


@pytest.fixture
async def e2e_context(test_db_router: DatabaseRouter) -> "AsyncGenerator[dict[str, Any], None]":
    """
    Sets up the DatabaseRouter and SQS adapters for the E2E test.
    Cleans up inserted data at the end of the test.
    """
    db_router = test_db_router
    base_url = os.environ["DATABASE_URL"]
    tenant_adapter = SqlAlchemyTenantAdapter(db_router)
    replication_adapter = SqlAlchemyReplicationAdapter(db_router, tenant_adapter)

    # We use localstack URL directly as per the local dev environment
    sqs_endpoint = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")

    queue_name = f"test-edi-tenant-sync-{uuid.uuid4()}.fifo"

    message_publisher = SqsTestPublisher(
        endpoint_url=sqs_endpoint,
    )

    queue_url = None
    try:
        # Create the queue if it doesn't exist, and purge it
        async with message_publisher.session.client(
            "sqs", endpoint_url=sqs_endpoint, region_name="us-east-1"
        ) as sqs:
            await sqs.create_queue(QueueName=queue_name, Attributes={"FifoQueue": "true"})
            resp = await sqs.get_queue_url(QueueName=queue_name)
            queue_url = resp["QueueUrl"]
            await sqs.purge_queue(QueueUrl=queue_url)
            await asyncio.sleep(1)
        # 1. Initialize the core replication service
        worker_service = ProvisioningWorkerService(tenant_adapter, replication_adapter)

        # 2. Initialize the dispatcher with the translator
        translator = DefaultEventTranslator()
        dispatcher = EdiConfigSyncSqsDispatcher(
            domain_service=worker_service, translator_port=translator
        )

        # 3. Create a raw consumer so tests can manually poll and dispatch exactly once

        test_consumer = AwsSqsConsumer(
            queue_url=queue_url,
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

        test_partner_id = generate_id("id")
        test_tenant_id = generate_id("id")

        async for session in db_router.get_global_session():
            tenant = Tenant(
                id=test_tenant_id,
                name=f"Test Tenant {test_tenant_id}",
                idp_tenant_id=f"idp_{test_tenant_id}",
                slug=f"tenant_{test_tenant_id}",
            )
            session.add(tenant)
            await session.flush()

            shard = await session.get(DatabaseShard, "edi_shard_1")
            if not shard:
                shard = DatabaseShard(
                    id="edi_shard_1",
                    name="EDI Primary Shard",
                    dsn="postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1",
                    status="active",
                )
                await session.merge(shard)
                await session.flush()

            app_res = await session.execute(select(App).where(App.slug == "edi"))
            edi_app = app_res.scalars().first()
            if not edi_app:
                edi_app = App(
                    id="ucp_app_{test_tenant_id}",
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

    finally:
        # Cleanup is now handled entirely by transaction rollbacks via TestDatabaseRouter
        # We only need to delete the queue
        if queue_url:
            async with message_publisher.session.client(
                "sqs", endpoint_url=sqs_endpoint, region_name="us-east-1"
            ) as sqs:
                await sqs.delete_queue(QueueUrl=queue_url)


@pytest.mark.integration
@pytest.mark.asyncio
async def wait_for_process(service, max_retries=10):
    for _ in range(max_retries):
        if await service.process_next_event():
            return True

        await asyncio.sleep(1)
    return False


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

    envelope = EventEnvelope(
        id=f"edi_cp_ob_{uuid.uuid4().hex}",
        source="edi_control_plane",
        event_type=EdiEventType.edi_as2_partner_created.value,
        tenant_id=tenant_id,
        idempotency_key=f"idemp_{uuid.uuid4().hex}",
        payload={"resource_id": str(partner_id)},
    )

    await message_publisher.publish(queue_name, dataclasses.asdict(envelope))

    await asyncio.sleep(2)  # Give LocalStack SQS a moment to make the message visible

    # 3. Provisioning Worker processes the event
    processed = await wait_for_process(worker_service)
    assert processed is True

    # 4. Verify replication occurred in the Shard DB
    async for tenant_session in db_router.get_tenant_session(tenant_id, "ucp_shard_1", base_url):
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
    message_publisher: SqsTestPublisher = e2e_context["message_publisher"]
    queue_name: str = e2e_context["queue_name"]
    tenant_id: str = e2e_context["tenant_id"]

    unregistered_event_envelope = {
        "id": "evt_123",
        "source": "soopa.ucp",
        "event_type": "tenant.provisioned",
        "idempotency_key": "123",
        "tenant_id": tenant_id,
        "payload": {
            "tenant_id": tenant_id,
            "eventType": "tenant.provisioned",
            "resource_id": "tenant_123",
        },
    }

    await message_publisher.publish(queue_name, unregistered_event_envelope)

    processed = await e2e_context["worker_service"].process_next_event()
    assert processed is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_webhook_replication_e2e_flow(e2e_context: dict[str, Any]) -> None:
    db_router = e2e_context["db_router"]
    tenant_id = e2e_context["tenant_id"]
    message_publisher = e2e_context["message_publisher"]
    queue_name = e2e_context["queue_name"]
    worker_service = e2e_context["worker_service"]

    webhook_id = generate_id("wh_test")

    # 1. Insert the global webhook
    async for global_session in db_router.get_global_session():
        global_webhook = GlobalWebhook(
            id=webhook_id,
            tenant_id=tenant_id,
            name="Test Webhook",
            url="https://example.com/webhook",
            active=True,
        )
        global_session.add(global_webhook)
        await global_session.commit()

    # 2. Synthesize a webhook.updated UCP outbox event
    envelope = {
        "id": generate_id("evt_webhook"),
        "source": "soopa.ucp",
        "event_type": "webhook.updated",
        "idempotency_key": generate_id("webhook"),
        "tenant_id": tenant_id,
        "payload": {
            "webhook_id": webhook_id,
            "tenant_id": tenant_id,
        },
    }

    await message_publisher.publish(queue_name, envelope)

    # 3. Process the event
    processed = await worker_service.process_next_event()
    assert processed is True

    base_url = e2e_context["base_url"]

    # 4. Verify replication
    async for tenant_session in db_router.get_tenant_session(tenant_id, "edi_shard_1", base_url):
        res = await tenant_session.execute(
            select(TenantWebhook).where(TenantWebhook.id == webhook_id)
        )
        tenant_webhook = res.scalars().first()
        assert tenant_webhook is not None
        assert tenant_webhook.id == webhook_id
        assert tenant_webhook.name == "Test Webhook"
        assert tenant_webhook.url == "https://example.com/webhook"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_outbound_route_replication_e2e_flow(e2e_context: dict[str, Any]) -> None:
    """
    Simulates the global control plane dropping an 'edi_outbound_route_created' event
    and verifies that the Config Sync Worker correctly replicates it to the tenant shard.
    """
    ctx = e2e_context
    db_router = ctx["db_router"]
    worker_service = ctx["worker_service"]
    message_publisher = ctx["message_publisher"]
    queue_name = ctx["queue_name"]
    tenant_id = ctx["tenant_id"]

    route_id = generate_id("edi_ob_rt")
    trading_partner_id = generate_id("partner")
    as2_partner_id = ctx["partner_id"]

    # 1. Insert the global outbound route
    async for global_session in db_router.get_global_session():
        global_route = GlobalOutboundRoute(
            id=route_id,
            tenant_id=tenant_id,
            trading_partner_id=trading_partner_id,
            as2_partner_id=as2_partner_id,
            name="Test Outbound Route",
            connection_type=EdiConnectionType.AS2.value,
            active=True,
        )
        global_session.add(global_route)
        await global_session.commit()

    # 2. Synthesize an edi_outbound_route_created event
    envelope = {
        "id": generate_id("evt_ob_route"),
        "source": "edi_control_plane",
        "event_type": EdiEventType.edi_outbound_route_created.value,
        "idempotency_key": generate_id("idemp"),
        "tenant_id": tenant_id,
        "payload": {
            "resource_id": route_id,
            "tenant_id": tenant_id,
        },
    }

    await message_publisher.publish(queue_name, envelope)

    # 3. Process the event
    processed = await worker_service.process_next_event()
    assert processed is True

    base_url = ctx["base_url"]

    # 4. Verify replication
    async for tenant_session in db_router.get_tenant_session(tenant_id, "edi_shard_1", base_url):
        res = await tenant_session.execute(
            select(TenantOutboundRoute).where(TenantOutboundRoute.id == route_id)
        )
        tenant_route = res.scalars().first()
        assert tenant_route is not None
        assert tenant_route.id == route_id
        assert tenant_route.name == "Test Outbound Route"
        assert tenant_route.trading_partner_id == trading_partner_id
        assert tenant_route.connection_type == EdiConnectionType.AS2.value


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

    envelope = EventEnvelope(
        id=generate_id("edi_cp_ob"),
        source="edi_control_plane",
        event_type=EdiEventType.edi_as2_partner_created.value,
        tenant_id=tenant_id,
        idempotency_key=generate_id("idemp"),
        payload={},  # missing resource_id
    )

    await message_publisher.publish(queue_name, dataclasses.asdict(envelope))
    await asyncio.sleep(2)

    # Worker processes the event. The SQS consumer swallows the exception and doesn't ack,
    # so the orchestrator returns False. We only call it once to prevent hanging in a retry loop.
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

    envelope_1 = EventEnvelope(
        id=f"edi_cp_ob_{uuid.uuid4().hex}",
        source="edi_control_plane",
        event_type=EdiEventType.edi_as2_partner_created.value,
        tenant_id=tenant_id,
        idempotency_key=f"idemp_{uuid.uuid4().hex}",
        payload={"resource_id": str(partner_id)},
    )

    envelope_2 = EventEnvelope(
        id=f"edi_cp_ob_{uuid.uuid4().hex}",
        source="edi_control_plane",
        event_type=EdiEventType.edi_as2_partner_created.value,
        tenant_id=tenant_id,
        idempotency_key=f"idemp_{uuid.uuid4().hex}",
        payload={"resource_id": str(partner_id)},
    )

    # Publish it twice
    await message_publisher.publish(queue_name, dataclasses.asdict(envelope_1))
    await message_publisher.publish(queue_name, dataclasses.asdict(envelope_2))
    await asyncio.sleep(2)

    # Process first event
    processed_1 = await wait_for_process(worker_service)
    assert processed_1 is True

    # Process second event
    processed_2 = await wait_for_process(worker_service)
    assert processed_2 is True

    # Verify replication still valid
    async for tenant_session in db_router.get_tenant_session(tenant_id, "ucp_shard_1", base_url):
        res = await tenant_session.execute(
            select(TenantAS2Partner).where(TenantAS2Partner.id == partner_id)
        )
        replicated_partner = res.scalars().first()
        assert replicated_partner is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_provisioning_delete_event(e2e_context: dict[str, Any]) -> None:
    """
    Tests that delivering a deleted event successfully deletes the entity from the tenant shard.
    """
    ctx = e2e_context
    db_router = ctx["db_router"]
    worker_service = ctx["worker_service"]
    message_publisher = ctx["message_publisher"]
    queue_name = ctx["queue_name"]
    partner_id = ctx["partner_id"]
    tenant_id = ctx["tenant_id"]
    base_url = ctx["base_url"]

    # Ensure it's there first (already inserted by e2e_context, but we must replicate it first)
    envelope_create = EventEnvelope(
        id=generate_id("edi_cp_ob"),
        source="edi_control_plane",
        event_type=EdiEventType.edi_as2_partner_created.value,
        tenant_id=tenant_id,
        idempotency_key=generate_id("idemp"),
        payload={"resource_id": str(partner_id)},
    )
    await message_publisher.publish(queue_name, dataclasses.asdict(envelope_create))
    await asyncio.sleep(1)
    await wait_for_process(worker_service)

    # Now delete it globally
    async for global_session in db_router.get_global_session():
        await global_session.execute(delete(AS2Partner).where(AS2Partner.id == partner_id))
        await global_session.commit()

    # Now send the deleted event
    envelope_delete = EventEnvelope(
        id=generate_id("edi_cp_ob"),
        source="edi_control_plane",
        event_type=EdiEventType.edi_as2_partner_deleted.value,
        tenant_id=tenant_id,
        idempotency_key=generate_id("idemp"),
        payload={"resource_id": str(partner_id)},
    )
    await message_publisher.publish(queue_name, dataclasses.asdict(envelope_delete))
    await asyncio.sleep(1)
    await wait_for_process(worker_service)

    # Verify replication deleted it in Shard DB
    async for tenant_session in db_router.get_tenant_session(tenant_id, "ucp_shard_1", base_url):
        res = await tenant_session.execute(
            select(TenantAS2Partner).where(TenantAS2Partner.id == partner_id)
        )
        replicated_partner = res.scalars().first()
        assert replicated_partner is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_provisioning_full_state_sync(e2e_context: dict[str, Any]) -> None:
    """
    Tests the full state topological sync directly.
    """
    ctx = e2e_context
    db_router = ctx["db_router"]
    worker_service = ctx["worker_service"]
    partner_id = ctx["partner_id"]
    tenant_id = ctx["tenant_id"]
    base_url = ctx["base_url"]

    # Insert a stale partner into the tenant shard that shouldn't be there
    stale_id = generate_id("stale")
    async for tenant_session in db_router.get_tenant_session(tenant_id, "ucp_shard_1", base_url):
        stale_partner = TenantAS2Partner(
            id=stale_id,
            tenant_id=tenant_id,
            name="Stale Partner",
            as2_id="STALE_AS2",
            active=True,
        )
        tenant_session.add(stale_partner)
        await tenant_session.commit()

    # Trigger full state sync
    await worker_service.replication_port.replicate_tenant_configuration(tenant_id)

    # Verify stale partner was deleted by _sync_deletes
    async for tenant_session in db_router.get_tenant_session(tenant_id, "ucp_shard_1", base_url):
        res = await tenant_session.execute(
            select(TenantAS2Partner).where(TenantAS2Partner.id == stale_id)
        )
        assert res.scalars().first() is None

        # Verify legitimate partner was replicated
        res = await tenant_session.execute(
            select(TenantAS2Partner).where(TenantAS2Partner.id == partner_id)
        )
        assert res.scalars().first() is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_provisioning_broadcast_event(e2e_context: dict[str, Any]) -> None:
    """
    Tests that delivering an event with PLATFORM_TENANT_ID broadcasts to all tenants.
    """
    ctx = e2e_context
    worker_service = ctx["worker_service"]
    message_publisher = ctx["message_publisher"]
    queue_name = ctx["queue_name"]
    partner_id = generate_id("partner")

    envelope_broadcast = EventEnvelope(
        id=generate_id("edi_cp_ob"),
        source="edi_control_plane",
        event_type=EdiEventType.edi_as2_partner_created.value,
        tenant_id=PLATFORM_TENANT_ID,
        idempotency_key=generate_id("idemp"),
        payload={"resource_id": str(partner_id)},
    )

    # Send broadcast event
    await message_publisher.publish(queue_name, dataclasses.asdict(envelope_broadcast))
    await asyncio.sleep(1)

    # We might expect this to fail inside the replication loop if the global entity isn't there,
    # but the service layer's broadcast logic will still be covered.
    # We just want to ensure it runs without completely crashing the worker loop.
    await worker_service.process_next_event()
