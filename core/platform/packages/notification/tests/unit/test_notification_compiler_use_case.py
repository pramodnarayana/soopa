import hashlib

import pytest

from notification.application.notification_compiler_use_case import NotificationCompilerUseCase
from notification.domain.models import (
    Channel,
    NotificationEvent,
    Template,
)
from tests.fakes import (
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

    uc = NotificationCompilerUseCase(
        template_repo, renderer, outbox, routes, user_prefs, record_repo
    )

    tenant_id = "t1"
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
    assert saved.event_type == f"{Channel.EMAIL.value}.requested"
    assert saved.payload["channel"] == Channel.EMAIL.value
    assert saved.payload["subject"] == "Invoice 123"
    assert saved.payload["content"] == "Hello, invoice 123 is ready."

    expected_idemp_input = f"t1:invoice.created:{Channel.EMAIL.value}:evt1"
    expected_idemp = hashlib.sha256(expected_idemp_input.encode()).hexdigest()
    assert saved.idempotency_key == expected_idemp


@pytest.mark.asyncio
async def test_dispatch_no_routes():
    uc = NotificationCompilerUseCase(
        FakeTemplateRepo(),
        FakeTemplateRenderer(),
        FakeOutboxRepo(),
        FakeRouteRepo(),
        FakeUserPrefRepo(),
        FakeRecordRepo(),
    )

    event = NotificationEvent(tenant_id="t1", event_type="unknown", data={})

    await uc.execute(event)
    assert len(uc.outbox_repo.events) == 0
