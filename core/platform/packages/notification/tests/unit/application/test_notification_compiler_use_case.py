import hashlib
import uuid

import pytest

from notification.application.notification_compiler_use_case import NotificationCompilerUseCase
from notification.domain.models import (
    Channel,
    NotificationEvent,
    Template,
)
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
async def test_dispatch_success():
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

    tenant_id = f"t1-{uuid.uuid4().hex[:8]}"
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
    event = NotificationEvent(
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
async def test_dispatch_no_routes():
    uow = FakeNotificationUow(
        user_preference_repo=FakeUserPrefRepo(),
        template_repo=FakeTemplateRepo(),
        record_repo=FakeRecordRepo(),
        route_repo=FakeRouteRepo(),
        outbox_repo=FakeOutboxRepo(),
    )
    uc = NotificationCompilerUseCase(uow=uow, template_renderer=FakeTemplateRenderer())

    event = NotificationEvent(tenant_id="t1", event_type="unknown", data={})

    await uc.execute(event)
    assert len(uc.uow.outbox_repo.events) == 0


@pytest.mark.asyncio
async def test_only_in_app_channel_creates_notification_record():
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
    tenant_id = f"t1-{uuid.uuid4().hex[:8]}"
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
        NotificationEvent(
            tenant_id=tenant_id,
            event_type=event_type,
            data={"id": "123", "event_id": "evt1"},
        )
    )

    assert len(outbox.events) == 2
    assert len(record_repo.records) == 1
    assert record_repo.records[0][1] == "Invoice 123 is ready."
