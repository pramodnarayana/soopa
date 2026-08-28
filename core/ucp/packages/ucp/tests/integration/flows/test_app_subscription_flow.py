import asyncio
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from database.events import EventEnvelope
from outbox.adapters.inbound.postgres_outbox_relay import PostgresOutboxRelay
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase
from pubsub.testing.in_memory_event_bus import InMemoryEventBus
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.subscriptions import App

from ucp.adapters.inbound.workers.ucp_event_dispatcher import UcpEventDispatcher
from ucp.adapters.outbound.database.postgres_outbox_repository import PostgresOutboxRepository
from ucp.adapters.outbound.database.uow import SqlAlchemyUcpUnitOfWork
from ucp.application.dto import SubscribeAppCommand
from ucp.application.use_cases.infrastructure_provisioner import InfrastructureProvisioner
from ucp.application.use_cases.provision_tenant_use_case import (
    ProvisionTenantCommand,
    ProvisionTenantUseCase,
)
from ucp.application.use_cases.subscribe_app_use_case import SubscribeAppUseCase

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def uow(db_session: AsyncSession) -> SqlAlchemyUcpUnitOfWork:
    return SqlAlchemyUcpUnitOfWork(session=db_session)


@pytest.mark.asyncio
async def test_app_subscription_flow(
    db_session: AsyncSession,
    uow: SqlAlchemyUcpUnitOfWork,
    localstack_container: dict[str, str],
    postgres_container,
) -> None:
    # 1. Setup Ports
    outbox_repo = PostgresOutboxRepository(lambda: db_session)

    # Use InMemoryEventBus instead of AWS SNS/SQS
    event_bus = InMemoryEventBus()

    db_url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    )

    outbox_processor = OutboxProcessorUseCase(
        repository=outbox_repo,
        publisher=event_bus,  # type: ignore[arg-type]
    )

    relay = PostgresOutboxRelay(
        processor=outbox_processor,
        database_url=db_url,
        listen_channel="ucp_outbox_wakeup",
    )

    dispatcher = UcpEventDispatcher()

    # Fake uow factory for the provisioner
    @asynccontextmanager
    async def fake_uow_factory():
        yield SqlAlchemyUcpUnitOfWork(session=db_session)

    provisioner = InfrastructureProvisioner(uow_factory=fake_uow_factory)

    dispatcher.subscribe("app.subscribed", provisioner.handle_app_subscribed)

    # 1.5 Get the seeded "edi" app from the database
    async with db_session.begin():
        stmt = select(App.id).where(App.slug == "edi")
        result = await db_session.execute(stmt)
        edi_app_id = result.scalar_one()

    # 2. Trigger Business Logic (Provision Tenant)
    use_case = ProvisionTenantUseCase(uow=uow)
    command = ProvisionTenantCommand(
        name="Stark Industries",
        creator_id="usr_mock",
    )

    tenant = await use_case.execute(command)

    # 3. Simulate UI passing an App ID to the SubscribeAppUseCase
    subscribe_use_case = SubscribeAppUseCase(uow=uow)
    subscribe_command = SubscribeAppCommand(tenant_id=tenant.id, app_id=edi_app_id)
    await subscribe_use_case.execute(subscribe_command)

    # 3. Process Outbox
    # First manually clear out any previous test events or claims if they leaked
    await db_session.execute(
        text(
            "UPDATE ucp.outbox SET status = 'PENDING', owner_token = NULL, lease_expires_at = NULL"
        )
    )
    await db_session.commit()

    # Fetch pending and publish
    await relay.processor.process_pending()

    # Wait for processing
    await asyncio.sleep(0.5)

    # 4. Execute Dispatcher for app.subscribed
    found_app_subscribed = False

    # Drain the in-memory bus
    for _ in range(5):
        async with event_bus.poll_raw_message() as ackable_msg:
            if not ackable_msg:
                continue

            raw_event = ackable_msg.payload
            print(f"DEBUG RAW EVENT: {raw_event}")

            if raw_event.get("tenant_id") != tenant.id:
                await ackable_msg.ack()
                continue

            event = EventEnvelope(
                id=raw_event.get("id", ""),
                source=raw_event.get("source", ""),
                tenant_id=raw_event.get("tenant_id", ""),
                event_type=raw_event.get("event_type", ""),
                idempotency_key=raw_event.get("idempotency_key"),
                payload=raw_event.get("payload", {}),
            )

            try:
                await dispatcher._dispatch(event)
                await ackable_msg.ack()
                if event.event_type == "app.subscribed":
                    found_app_subscribed = True
            except Exception:  # noqa: BLE001
                await ackable_msg.nack()

    assert found_app_subscribed, "app.subscribed event was never received from SQS"

    # 5. Verify InfrastructureProvisioner Side Effects
    # The provisioner creates ShardRegistry and AppSubscription records in the global schema.
    # Let's verify the Shard was created.
    res = await db_session.execute(
        text("SELECT * FROM ucp.shard_registry WHERE tenant_id = :tenant_id"),
        {"tenant_id": tenant.id},
    )
    shard = res.fetchone()
    assert shard is not None
    assert shard.shard_id == "edi_shard_1"

    # Verify App Subscription status
    res = await db_session.execute(
        text(
            "SELECT * FROM ucp.app_subscriptions WHERE tenant_id = :tenant_id AND app_id = :app_id"
        ),
        {"tenant_id": tenant.id, "app_id": edi_app_id},
    )
    app_sub = res.fetchone()
    assert app_sub is not None
    assert app_sub.status == "active"
