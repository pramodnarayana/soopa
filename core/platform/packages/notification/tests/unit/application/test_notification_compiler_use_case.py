import hashlib

import pytest
from seedwork import generate_random_hex

from notification.application.notification_compiler_use_case import (
    CompileNotificationCommand,
    NotificationCompilerUseCase,
)
from notification.domain.enums import Channel
from notification.domain.template import Template
from notification.facade import notify
from notification.testing.fakes import (
    FakeNotificationUow,
    FakeOutboxRepo,
    FakeRecordRepo,
    FakeRouteRepo,
    FakeTemplateRenderer,
    FakeTemplateRepo,
    FakeUserPrefRepo,
)


@pytest.mark.asyncio
async def test_dispatch_success() -> None:
    template_repo = FakeTemplateRepo()
    renderer = FakeTemplateRenderer()
    outbox = FakeOutboxRepo()
    routes = FakeRouteRepo()
    user_prefs = FakeUserPrefRepo()
    record_repo = FakeRecordRepo()

    uow = FakeNotificationUow(
        user_preference_repo=user_prefs,
        template_repo=template_repo,
        record_repo=record_repo,
        route_repo=routes,
        outbox_repo=outbox,
    )
    uc = NotificationCompilerUseCase(uow=uow, template_renderer=renderer)

    tenant_id = f"t1-{generate_random_hex(6)}"
    event_type = "invoice.created"

    # Setup Fakes
    routes.routes[(tenant_id, event_type)] = [Channel.EMAIL, Channel.IN_APP]

    template_repo.templates[(tenant_id, event_type, Channel.EMAIL)] = Template(
        id="tmpl_1",
        tenant_id=tenant_id,
        name="Invoice Created - Email",
        event_type=event_type,
        subject="Invoice {{id}}",
        body_content="Hello, invoice {{id}} is ready.",
        channel=Channel.EMAIL,
    )

    # Missing template for IN_APP, should skip gracefully

    # Execute
    event = CompileNotificationCommand(
        tenant_id=tenant_id, event_type=event_type, data={"id": "123", "event_id": "evt1"}
    )

    await uc.execute(event)

    # Assert
    assert len(outbox.events) == 1
    saved = outbox.events[0]
    assert saved.tenant_id == tenant_id
    assert saved.event_type == "email.requested"
    assert saved.payload["channel"] == Channel.EMAIL.value
    assert saved.payload["subject"] == "Invoice 123"
    assert saved.payload["content"] == "Hello, invoice 123 is ready."

    expected_idemp_input = f"{tenant_id}:invoice.created:{Channel.EMAIL.value}:evt1"
    expected_idemp = hashlib.sha256(expected_idemp_input.encode()).hexdigest()
    assert saved.idempotency_key == expected_idemp


@pytest.mark.asyncio
async def test_dispatch_no_routes() -> None:
    outbox = FakeOutboxRepo()
    uow = FakeNotificationUow(
        user_preference_repo=FakeUserPrefRepo(),
        template_repo=FakeTemplateRepo(),
        record_repo=FakeRecordRepo(),
        route_repo=FakeRouteRepo(),
        outbox_repo=outbox,
    )
    uc = NotificationCompilerUseCase(uow=uow, template_renderer=FakeTemplateRenderer())

    event = CompileNotificationCommand(tenant_id="t1", event_type="unknown", data={})

    await uc.execute(event)
    assert len(outbox.events) == 0


@pytest.mark.asyncio
async def test_only_in_app_channel_creates_notification_record() -> None:
    template_repo = FakeTemplateRepo()
    renderer = FakeTemplateRenderer()
    outbox = FakeOutboxRepo()
    routes = FakeRouteRepo()
    record_repo = FakeRecordRepo()
    user_prefs = FakeUserPrefRepo()
    uow = FakeNotificationUow(
        user_preference_repo=user_prefs,
        template_repo=template_repo,
        record_repo=record_repo,
        route_repo=routes,
        outbox_repo=outbox,
    )
    uc = NotificationCompilerUseCase(uow=uow, template_renderer=renderer)
    tenant_id = f"t1-{generate_random_hex(6)}"
    event_type = "invoice.created"
    routes.routes[(tenant_id, event_type)] = [Channel.EMAIL, Channel.IN_APP]
    for channel in (Channel.EMAIL, Channel.IN_APP):
        template_repo.templates[(tenant_id, event_type, channel)] = Template(
            id=f"tmpl-{channel.value}",
            tenant_id=tenant_id,
            name=f"Invoice Created - {channel.value}",
            event_type=event_type,
            subject="Invoice {{id}}",
            body_content="Invoice {{id}} is ready.",
            channel=channel,
        )

    await uc.execute(
        CompileNotificationCommand(
            tenant_id=tenant_id,
            event_type=event_type,
            data={"id": "123", "event_id": "evt1"},
        )
    )

    assert len(outbox.events) == 2
    assert len(record_repo.records) == 1
    assert record_repo.records[0][1] == "Invoice 123 is ready."


@pytest.mark.asyncio
async def test_distinct_notifications_without_event_id_never_collide_while_retries_stay_deterministic() -> (
    None
):
    template_repo = FakeTemplateRepo()
    renderer = FakeTemplateRenderer()
    outbox = FakeOutboxRepo()
    routes = FakeRouteRepo()
    record_repo = FakeRecordRepo()
    uow = FakeNotificationUow(
        user_preference_repo=FakeUserPrefRepo(),
        template_repo=template_repo,
        record_repo=record_repo,
        route_repo=routes,
        outbox_repo=outbox,
    )
    uc = NotificationCompilerUseCase(uow=uow, template_renderer=renderer)
    tenant_id = f"t1-{generate_random_hex(6)}"
    event_type = "sync.alert"
    routes.routes[(tenant_id, event_type)] = [Channel.EMAIL]
    template_repo.templates[(tenant_id, event_type, Channel.EMAIL)] = Template(
        id="tmpl-email",
        tenant_id=tenant_id,
        name="Sync Alert",
        event_type=event_type,
        subject="Alert",
        body_content="Body",
        channel=Channel.EMAIL,
    )

    # 1. Stage-1 notify() always guarantees a non-empty idempotency_key even when omitted by caller
    env_1 = notify(
        tenant_id=tenant_id,
        source="billing.invoicing",
        notification_type=event_type,
        notification_data={"run_id": "run_1"},
    )
    env_2 = notify(
        tenant_id=tenant_id,
        source="billing.invoicing",
        notification_type=event_type,
        notification_data={"run_id": "run_2"},
    )
    assert env_1.idempotency_key is not None and len(env_1.idempotency_key) > 0
    assert env_2.idempotency_key is not None and env_2.idempotency_key != env_1.idempotency_key

    # 2. Envelope-level idempotency_key produces distinct outbox dedupe keys across separate notifications,
    #    and identical deterministic keys across retries of the same notification!
    cmd_1 = CompileNotificationCommand(
        tenant_id=tenant_id,
        event_type=event_type,
        data={"run_id": "run_1"},
        idempotency_key=env_1.idempotency_key,
    )
    cmd_1_retry = CompileNotificationCommand(
        tenant_id=tenant_id,
        event_type=event_type,
        data={"run_id": "run_1"},
        idempotency_key=env_1.idempotency_key,
    )
    cmd_2 = CompileNotificationCommand(
        tenant_id=tenant_id,
        event_type=event_type,
        data={"run_id": "run_2"},
        idempotency_key=env_2.idempotency_key,
    )

    await uc.execute(cmd_1)
    await uc.execute(cmd_1_retry)
    await uc.execute(cmd_2)

    assert outbox.events[0].idempotency_key == outbox.events[1].idempotency_key
    assert outbox.events[2].idempotency_key != outbox.events[0].idempotency_key

    # 3. Direct in-process calls with neither idempotency_key nor data['event_id'] must also never collide
    await uc.execute(
        CompileNotificationCommand(tenant_id=tenant_id, event_type=event_type, data={})
    )
    await uc.execute(
        CompileNotificationCommand(tenant_id=tenant_id, event_type=event_type, data={})
    )
    assert outbox.events[3].idempotency_key != outbox.events[4].idempotency_key
