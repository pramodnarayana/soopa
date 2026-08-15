import hashlib

import pytest

from notification.application.dispatch_use_case import DispatchNotificationUseCase
from notification.domain.models import (
    Channel,
    NotificationEvent,
    NotificationOutboxEvent,
    Template,
    UserNotificationPreference,
)
from notification.ports.interfaces import (
    NotificationRouteRepositoryPort,
    TemplateRendererPort,
    TemplateRepositoryPort,
    UserNotificationPreferenceRepositoryPort,
)
from notification.ports.outbox_repository import NotificationOutboxRepositoryPort


class FakeUserPrefRepo(UserNotificationPreferenceRepositoryPort):
    def __init__(self):
        self.prefs = {}

    async def get_preference(
        self, tenant_id: str, user_id: str, event_type: str, channel: str
    ) -> UserNotificationPreference | None:
        return self.prefs.get((tenant_id, user_id, event_type, channel))

    async def get_user_preferences(
        self, tenant_id: str, user_id: str
    ) -> list[UserNotificationPreference]:
        return [p for p in self.prefs.values() if p.tenant_id == tenant_id and p.user_id == user_id]

    async def save_preference(self, preference: UserNotificationPreference) -> None:
        self.prefs[(preference.tenant_id, preference.user_id, preference.event_type, preference.channel.value)] = preference


class FakeTemplateRepo(TemplateRepositoryPort):
    def __init__(self):
        self.templates = {}

    async def get_template(
        self, tenant_id: str, event_type: str, channel: Channel
    ) -> Template | None:
        return self.templates.get((tenant_id, event_type, channel))


class FakeTemplateRenderer(TemplateRendererPort):
    def render(self, template_str: str, context: dict) -> str:
        # Simple string replacement for testing
        result = template_str
        for k, v in context.items():
            result = result.replace(f"{{{{{k}}}}}", str(v))
        return result


class FakeOutboxRepo(NotificationOutboxRepositoryPort):
    def __init__(self):
        self.events = []

    async def save(self, event: NotificationOutboxEvent) -> None:
        self.events.append(event)


class FakeRouteRepo(NotificationRouteRepositoryPort):
    def __init__(self):
        self.routes = {}

    async def get_channels(self, tenant_id: str, event_type: str) -> list[Channel]:
        return self.routes.get((tenant_id, event_type), [])


@pytest.mark.asyncio
async def test_dispatch_success():
    template_repo = FakeTemplateRepo()
    renderer = FakeTemplateRenderer()
    outbox = FakeOutboxRepo()
    routes = FakeRouteRepo()
    user_prefs = FakeUserPrefRepo()

    uc = DispatchNotificationUseCase(template_repo, renderer, outbox, routes, user_prefs)

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
    assert saved.event_type == event_type
    assert saved.payload["channel"] == Channel.EMAIL.value
    assert saved.payload["subject"] == "Invoice 123"
    assert saved.payload["content"] == "Hello, invoice 123 is ready."

    expected_idemp_input = f"t1:invoice.created:{Channel.EMAIL.value}:evt1"
    expected_idemp = hashlib.sha256(expected_idemp_input.encode()).hexdigest()
    assert saved.idempotency_key == expected_idemp


@pytest.mark.asyncio
async def test_dispatch_no_routes():
    uc = DispatchNotificationUseCase(
        FakeTemplateRepo(),
        FakeTemplateRenderer(),
        FakeOutboxRepo(),
        FakeRouteRepo(),
        FakeUserPrefRepo(),
    )

    event = NotificationEvent(tenant_id="t1", event_type="unknown", data={})

    await uc.execute(event)
    assert len(uc.outbox_repo.events) == 0
