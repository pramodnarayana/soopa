import asyncio
from unittest.mock import AsyncMock, create_autospec

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
from ucp.application.use_cases.identity_sync_service import IdentitySyncService
from ucp.application.use_cases.provision_tenant_use_case import (
    ProvisionTenantCommand,
    ProvisionTenantUseCase,
)
from ucp.application.use_cases.ucp_outbox_processor_use_case import UcpOutboxProcessorUseCase
from ucp.ports.outbound.identity_provider_port import IdentityProviderPort
from ucp.ports.outbound.user_identity_provider_port import UserIdentityProviderPort

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def uow(db_session: AsyncSession) -> SqlAlchemyUcpUnitOfWork:
    return SqlAlchemyUcpUnitOfWork(session=db_session)


@pytest.mark.asyncio
async def test_identity_sync_flow(
    db_session: AsyncSession,
    uow: SqlAlchemyUcpUnitOfWork,
    localstack_container: dict[str, str],
    postgres_container,
) -> None:
    # 1. Setup Mocks and Infrastructure Ports
    mock_idp = create_autospec(IdentityProviderPort, instance=True)
    mock_idp.sync_tenant = AsyncMock()

    mock_user_idp = create_autospec(UserIdentityProviderPort, instance=True)

    # Outbox Setup
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

    # Dispatcher Setup
    event_listener = SqsUcpEventListener(
        queue_url=localstack_container["sqs_queue_url"],
        endpoint_url=localstack_container["endpoint_url"],
    )
    dispatcher = UcpEventsSqsConsumer(event_listener)

    # Identity Sync Service (Pure Domain Handler)
    identity_service = IdentitySyncService(
        identity_provider=mock_idp, user_identity_provider=mock_user_idp
    )

    async def tenant_provisioned_handler(event) -> None:
        await identity_service.handle_tenant_provisioned(event.tenant_id)

    dispatcher.subscribe("tenant.provisioned", tenant_provisioned_handler)

    # 2. Trigger Business Logic (Provision Tenant)
    use_case = ProvisionTenantUseCase(uow=uow)
    command = ProvisionTenantCommand(
        name="Acme Corp",
    )

    tenant = await use_case.execute(command)

    # 3. Verify Outbox Event created in DB
    events = await outbox_repo.claim_next_events(
        worker_id="test-worker", limit=10, lock_lease_ms=10000
    )
    assert len(events) > 0
    tenant_provisioned_event = next(
        (e for e in events if e.event_type == "tenant.provisioned"), None
    )
    assert tenant_provisioned_event is not None

    # Release the claimed event so the relay can pick it up
    await db_session.execute(
        text(
            "UPDATE ucp.outbox SET status = 'PENDING', owner_token = NULL, lease_expires_at = NULL"
        )
    )
    await db_session.commit()
    await db_session.commit()

    # 4. Execute Outbox Relay (Publish to SNS)
    # The relay internally runs a listener, but we can also just call `poll`
    # directly for the integration test since we just pushed it to 'pending'.
    # But let's actually run the relay poll
    await relay.processor.process_pending()  # Fetch pending and publish

    # Wait for SQS to receive from SNS
    await asyncio.sleep(1)

    # 5. Execute SQS Dispatcher
    # We might have multiple events in the queue from previous tests.
    found_tenant_provisioned = False
    for _ in range(5):
        try:
            async with event_listener.process_next_event() as event:
                if not event or event.tenant_id != tenant.id:
                    continue
                await dispatcher._dispatch(event)
                if event.event_type == "tenant.provisioned":
                    found_tenant_provisioned = True
                    break
        except Exception:  # noqa: BLE001, S110
            pass

    assert found_tenant_provisioned, "tenant.provisioned event not found"
    mock_idp.sync_tenant.assert_called_once_with(tenant.id)
