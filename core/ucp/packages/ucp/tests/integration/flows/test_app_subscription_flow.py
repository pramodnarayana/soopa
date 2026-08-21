import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.adapters.inbound.workers.sqs_ucp_event_listener import SqsUcpEventListener
from ucp.adapters.inbound.workers.ucp_events_sqs_consumer import UcpEventsSqsConsumer
from ucp.adapters.inbound.workers.ucp_outbox_relay import UcpOutboxRelay
from ucp.adapters.outbound.database.postgres_outbox_repository import PostgresOutboxRepository
from ucp.adapters.outbound.database.uow import SqlAlchemyUcpUnitOfWork
from ucp.adapters.outbound.messaging.ucp_sns_outbox_publisher import UcpSnsOutboxPublisher
from ucp.application.use_cases.infrastructure_provisioner import InfrastructureProvisioner
from ucp.application.use_cases.provision_tenant_use_case import (
    ProvisionTenantCommand,
    ProvisionTenantUseCase,
)
from ucp.application.use_cases.subscribe_app_use_case import (
    SubscribeAppCommand,
    SubscribeAppUseCase,
)
from ucp.application.use_cases.ucp_outbox_processor_use_case import UcpOutboxProcessorUseCase

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
    outbox_repo = PostgresOutboxRepository(lambda: db_session)  # type: ignore
    sns_publisher = UcpSnsOutboxPublisher(
        topic_arn=localstack_container["sns_topic_arn"],
        endpoint_url=localstack_container["endpoint_url"],
    )

    db_url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    )

    outbox_processor = UcpOutboxProcessorUseCase(
        repository=outbox_repo,
        publisher=sns_publisher,
    )

    relay = UcpOutboxRelay(
        processor=outbox_processor,
        database_url=db_url,
    )

    event_listener = SqsUcpEventListener(
        queue_url=localstack_container["sqs_queue_url"],
        endpoint_url=localstack_container["endpoint_url"],
    )
    dispatcher = UcpEventsSqsConsumer(event_listener)

    # Fake session factory for the provisioner
    class FakeSessionFactory:
        def __call__(self):
            return db_session

    provisioner = InfrastructureProvisioner(session_factory=FakeSessionFactory())  # type: ignore

    dispatcher.subscribe("app.subscribed", provisioner.handle_app_subscribed)

    # 1.5 Seed the "edi" app and shard in the database
    from ucp_models.infrastructure import DatabaseShard
    from ucp_models.subscriptions import App

    async with db_session.begin():
        db_session.add(App(id="edi", name="EDI App", slug="edi", description=""))
        db_session.add(
            DatabaseShard(
                id="edi_shard_1", name="EDI Shard 1", dsn="postgresql://mock", status="active"
            )
        )

    # 2. Trigger Business Logic (Provision Tenant)
    use_case = ProvisionTenantUseCase(uow=uow)
    command = ProvisionTenantCommand(
        name="Stark Industries",
    )

    tenant = await use_case.execute(command)

    # Now subscribe the tenant to an app to trigger the app.subscribed event
    subscribe_use_case = SubscribeAppUseCase(uow=uow)
    subscribe_command = SubscribeAppCommand(tenant_id=tenant.id, app_id="edi")
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

    # Wait for SQS to receive from SNS
    await asyncio.sleep(1)

    # 4. Execute SQS Dispatcher for app.subscribed
    found_app_subscribed = False

    # We might have multiple events (TenantProvisioned, UserInvited, app.subscribed). Process up to 5.
    for _ in range(5):
        try:
            async with event_listener.process_next_event() as event:
                if not event or event.tenant_id != tenant.id:
                    continue
                await dispatcher._dispatch(event)
                if event.event_type == "app.subscribed":
                    found_app_subscribed = True
                    break
        except Exception:  # noqa: BLE001, S110
            pass

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
        text("SELECT * FROM ucp.app_subscriptions WHERE tenant_id = :tenant_id AND app_id = 'edi'"),
        {"tenant_id": tenant.id},
    )
    app_sub = res.fetchone()
    assert app_sub is not None
    assert app_sub.status == "active"
