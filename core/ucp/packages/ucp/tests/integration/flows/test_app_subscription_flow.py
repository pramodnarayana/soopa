import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from outbox.adapters.inbound.notify_outbox_relay import NotifyOutboxRelay
from outbox.adapters.outbound.sqlalchemy_global_outbox_repository import (
    SqlAlchemyGlobalOutboxRepository,
)
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase
from pubsub.testing.in_memory_event_bus import InMemoryEventBus
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.events import UcpOutbox
from ucp_models.sharding import ShardRegistry
from ucp_models.subscriptions import App, AppSubscription

from ucp.adapters.inbound.workers.ucp_event_dispatcher import UcpEventDispatcher
from ucp.adapters.outbound.database.uow import SqlAlchemyUcpUnitOfWork
from ucp.application.use_cases.app_subscription_manager import AppSubscriptionManager
from ucp.application.use_cases.provision_tenant_use_case import (
    ProvisionTenantCommand,
    ProvisionTenantUseCase,
)
from ucp.application.use_cases.subscribe_app_use_case import (
    SubscribeAppCommand,
    SubscribeAppUseCase,
)
from ucp.application.use_cases.unsubscribe_app_use_case import (
    UnsubscribeAppCommand,
    UnsubscribeAppUseCase,
)
from ucp.bootstrap.container import create_ucp_uow
from ucp.domain.constants import LifecycleStatus, UcpEventType, UcpOutboxSource

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def uow(db_session: AsyncSession) -> SqlAlchemyUcpUnitOfWork:
    return create_ucp_uow(session=db_session)


async def _drain_and_find_tenant_event(
    event_bus: InMemoryEventBus,
    dispatcher: UcpEventDispatcher,
    *,
    tenant_id: str,
    expected_event_type: str,
) -> bool:
    found = False
    for _ in range(5):
        async with event_bus.poll_raw_message() as ackable_msg:
            if not ackable_msg:
                continue

            raw_event = ackable_msg.payload
            if raw_event.get("tenant_id") != tenant_id:
                await ackable_msg.ack()
                continue

            raw_payload = raw_event.get("payload")
            payload: JsonDict = raw_payload if isinstance(raw_payload, dict) else {}
            event = EventEnvelope(
                id=str(raw_event.get("id", "")),
                source=str(raw_event.get("source", "")),
                tenant_id=str(raw_event.get("tenant_id", "")),
                event_type=str(raw_event.get("event_type", "")),
                idempotency_key=(
                    str(raw_event["idempotency_key"])
                    if raw_event.get("idempotency_key") is not None
                    else None
                ),
                payload=payload,
            )

            await dispatcher.dispatch(raw_event)
            await ackable_msg.ack()
            if event.event_type == expected_event_type:
                found = True
    return found


@pytest.mark.asyncio
async def test_app_subscription_flow(
    db_session: AsyncSession,
    uow: SqlAlchemyUcpUnitOfWork,
    localstack_container: dict[str, str],
) -> None:
    @asynccontextmanager
    async def session_scope() -> AsyncIterator[AsyncSession]:
        yield db_session

    outbox_repo = SqlAlchemyGlobalOutboxRepository(
        session_factory=session_scope,
        model_cls=UcpOutbox,
        source=UcpOutboxSource.UCP.value,
    )

    event_bus = InMemoryEventBus()
    db_url = os.environ["DATABASE_URL"]
    outbox_processor = OutboxProcessorUseCase(
        repository=outbox_repo,
        publisher=event_bus,
    )
    relay = NotifyOutboxRelay(
        processor=outbox_processor,
        database_url=db_url,
        listen_channel="ucp_outbox_wakeup",
    )

    dispatcher = UcpEventDispatcher()

    @asynccontextmanager
    async def fake_uow_factory() -> AsyncIterator[SqlAlchemyUcpUnitOfWork]:
        yield create_ucp_uow(session=db_session)

    provisioner = AppSubscriptionManager(uow_factory=fake_uow_factory)
    dispatcher.subscribe(UcpEventType.APP_SUBSCRIBED.value, provisioner.handle_app_subscribed)
    dispatcher.subscribe(UcpEventType.APP_UNSUBSCRIBED.value, provisioner.handle_app_unsubscribed)

    async with db_session.begin():
        await db_session.execute(
            text(
                "INSERT INTO ucp.database_shards (id, name, dsn, status, created_at, updated_at) "
                "VALUES ('edi_shard_1', 'EDI Primary', 'fake_dsn', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
                "ON CONFLICT DO NOTHING"
            )
        )
        await db_session.execute(
            text(
                "INSERT INTO ucp.apps (id, name, slug, description, created_at, updated_at) "
                "VALUES ('app_edi_core', 'EDI', 'edi', 'B2B EDI', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
                "ON CONFLICT DO NOTHING"
            )
        )
        stmt = select(App.id).where(App.slug == "edi")
        result = await db_session.execute(stmt)
        edi_app_id = result.scalar_one()

    use_case = ProvisionTenantUseCase(uow=uow)
    tenant = (await use_case.execute(ProvisionTenantCommand(name="Stark Industries"))).unwrap()

    subscribe_use_case = SubscribeAppUseCase(uow=uow)
    assert (
        await subscribe_use_case.execute(
            SubscribeAppCommand(tenant_id=tenant.id, app_id=edi_app_id)
        )
    ).is_ok

    await relay.processor.process_pending()
    await asyncio.sleep(0.5)

    found_app_subscribed = await _drain_and_find_tenant_event(
        event_bus,
        dispatcher,
        tenant_id=tenant.id,
        expected_event_type=UcpEventType.APP_SUBSCRIBED.value,
    )
    assert found_app_subscribed, "app.subscribed event was never received from SQS"

    shard_row = (
        await db_session.execute(
            select(ShardRegistry).where(
                ShardRegistry.tenant_id == tenant.id,
                ShardRegistry.app_id == edi_app_id,
            )
        )
    ).scalar_one_or_none()
    assert shard_row is not None
    assert shard_row.shard_id == "edi_shard_1"
    assert shard_row.status == LifecycleStatus.ACTIVE.value

    unsubscribe_use_case = UnsubscribeAppUseCase(uow=uow)
    assert (
        await unsubscribe_use_case.execute(
            UnsubscribeAppCommand(tenant_id=tenant.id, app_id=edi_app_id)
        )
    ).is_ok

    await relay.processor.process_pending()
    await asyncio.sleep(0.5)

    found_app_unsubscribed = await _drain_and_find_tenant_event(
        event_bus,
        dispatcher,
        tenant_id=tenant.id,
        expected_event_type=UcpEventType.APP_UNSUBSCRIBED.value,
    )
    assert found_app_unsubscribed, "app.unsubscribed event was never received from SQS"

    app_sub = (
        await db_session.execute(
            select(AppSubscription).where(
                AppSubscription.tenant_id == tenant.id,
                AppSubscription.app_id == edi_app_id,
            )
        )
    ).scalar_one_or_none()
    assert app_sub is not None
    assert app_sub.status == LifecycleStatus.INACTIVE.value

    unsubscribed_shard = (
        await db_session.execute(
            select(ShardRegistry).where(
                ShardRegistry.tenant_id == tenant.id,
                ShardRegistry.app_id == edi_app_id,
            )
        )
    ).scalar_one_or_none()
    assert unsubscribed_shard is not None
    assert unsubscribed_shard.status == LifecycleStatus.INACTIVE.value
